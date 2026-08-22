"""Local schedules with bounded recurrence expansion and durable notification de-duplication."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Awaitable, Callable

from pydantic import JsonValue

from agent_platform.core.interfaces import Tool
from agent_platform.models import DataLevel, RiskLevel, ToolContext, ToolMetadata, ToolReceipt
from agent_platform.tools.reminder_tool import ChineseTimeParser


logger = logging.getLogger(__name__)

_MAX_RANGE_DAYS = 31
_MAX_OCCURRENCES = 500


class ScheduleTool(Tool):
    """Persist local schedules; recurrence is expanded only inside a requested window."""

    def __init__(
        self,
        database_path: Path,
        timezone: str = "Asia/Shanghai",
        callback: Callable[[dict[str, JsonValue]], Awaitable[None]] | None = None,
    ) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(database_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA busy_timeout=5000")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.execute(
            """CREATE TABLE IF NOT EXISTS schedules(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                location TEXT NOT NULL DEFAULT '',
                start_at TEXT NOT NULL,
                end_at TEXT,
                recurrence TEXT NOT NULL DEFAULT 'none' CHECK(recurrence IN ('none', 'daily', 'weekly', 'monthly')),
                weekdays_json TEXT NOT NULL DEFAULT '[]',
                recurrence_until_at TEXT,
                status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'cancelled')),
                notify_before_minutes INTEGER NOT NULL DEFAULT 15 CHECK(notify_before_minutes BETWEEN 0 AND 1440),
                owner TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                cancelled_at TEXT
            )"""
        )
        self._connection.execute(
            """CREATE TABLE IF NOT EXISTS schedule_notifications(
                schedule_id INTEGER NOT NULL,
                occurrence_start_at TEXT NOT NULL,
                notified_at TEXT NOT NULL,
                PRIMARY KEY(schedule_id, occurrence_start_at),
                FOREIGN KEY(schedule_id) REFERENCES schedules(id)
            )"""
        )
        existing_columns = {str(row[1]) for row in self._connection.execute("PRAGMA table_info(schedules)")}
        if "owner" not in existing_columns:
            # Pre-gateway rows keep owner='' and are invisible to every account.
            self._connection.execute("ALTER TABLE schedules ADD COLUMN owner TEXT NOT NULL DEFAULT ''")
        self._connection.execute("DROP INDEX IF EXISTS idx_schedules_status_start")
        self._connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_schedules_owner_status_start ON schedules(owner, status, start_at)"
        )
        self._connection.commit()
        self._parser = ChineseTimeParser(timezone)
        self._callback = callback or self._log_callback
        self._lock = asyncio.Lock()
        self._scheduler_task: asyncio.Task[None] | None = None

    @staticmethod
    def _required_owner(context: ToolContext | None) -> str:
        if context is None or not context.owner:
            raise ValueError("schedule operations require an authenticated owner context")
        return context.owner

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="schedule_manage",
            description="Create, query, and cancel local schedules with bounded recurrence",
            parameters_schema={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["create", "query", "cancel"]},
                    "id": {"type": "integer", "minimum": 1},
                    "title": {"type": "string", "minLength": 1, "maxLength": 500},
                    "title_query": {"type": "string", "minLength": 1, "maxLength": 500},
                    "start_text": {"type": "string", "minLength": 1, "maxLength": 200},
                    "end_text": {"type": "string", "minLength": 1, "maxLength": 200},
                    "location": {"type": "string", "maxLength": 500},
                    "recurrence": {"type": "string", "enum": ["none", "daily", "weekly", "monthly"]},
                    "weekdays": {
                        "type": "array",
                        "items": {"type": "integer", "minimum": 0, "maximum": 6},
                        "minItems": 1,
                        "maxItems": 7,
                        "uniqueItems": True,
                    },
                    "recurrence_until_text": {"type": "string", "minLength": 1, "maxLength": 200},
                    "range": {"type": "string", "enum": ["today", "tomorrow", "this_week", "next_week", "custom"]},
                    "range_start": {"type": "string", "format": "date-time"},
                    "range_end": {"type": "string", "format": "date-time"},
                    "notify_before_minutes": {"type": "integer", "minimum": 0, "maximum": 1440},
                },
                "required": ["action"],
                "allOf": [
                    {
                        "if": {"properties": {"action": {"const": "create"}}, "required": ["action"]},
                        "then": {"required": ["title", "start_text"]},
                    },
                    {
                        "if": {"properties": {"action": {"const": "cancel"}}, "required": ["action"]},
                        "then": {"required": ["id"]},
                    },
                    {
                        "if": {"properties": {"recurrence": {"const": "weekly"}}, "required": ["recurrence"]},
                        "then": {"required": ["weekdays"]},
                    },
                    {
                        "if": {"properties": {"range": {"const": "custom"}}, "required": ["range"]},
                        "then": {"required": ["range_start", "range_end"]},
                    },
                ],
                "additionalProperties": False,
            },
            risk_level=RiskLevel.R1,
            data_level=DataLevel.D1,
            timeout_seconds=5,
        )

    def idempotency_key(self, arguments: dict[str, JsonValue]) -> str:
        if arguments.get("action") == "query":
            return f"schedule:query:{datetime.now(UTC).isoformat()}"
        value = json.dumps(arguments, ensure_ascii=False, sort_keys=True)
        return f"mutation:schedule:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"

    async def execute(self, arguments: dict[str, JsonValue], context: ToolContext | None = None) -> ToolReceipt:
        owner = self._required_owner(context)
        action = str(arguments["action"])
        if action == "create":
            return await self._create(arguments, owner)
        if action == "query":
            return await self._query(arguments, owner)
        if action == "cancel":
            return await self._cancel(int(arguments["id"]), arguments, owner)
        raise ValueError(f"Unsupported schedule action: {action}")

    @staticmethod
    def _to_item(row: sqlite3.Row) -> dict[str, JsonValue]:
        return {
            "id": int(row["id"]),
            "title": str(row["title"]),
            "location": str(row["location"]),
            "start_at": str(row["start_at"]),
            "end_at": str(row["end_at"]) if row["end_at"] is not None else None,
            "recurrence": str(row["recurrence"]),
            "weekdays": json.loads(str(row["weekdays_json"])),
            "recurrence_until_at": str(row["recurrence_until_at"]) if row["recurrence_until_at"] else None,
            "status": str(row["status"]),
            "notify_before_minutes": int(row["notify_before_minutes"]),
            "created_at": str(row["created_at"]),
            "cancelled_at": str(row["cancelled_at"]) if row["cancelled_at"] else None,
        }

    def _input_error(self, arguments: dict[str, JsonValue], field: str, message: str) -> ToolReceipt:
        return ToolReceipt(
            tool_name=self.metadata.name,
            actual_arguments=arguments,
            success=True,
            output_summary=message,
            output={"requires_confirmation": True, "confirmation_type": "missing_fields", "fields": [field], "message": message},
            next_actions=["补充明确的日程时间后重试"],
        )

    def _parse_create(
        self, arguments: dict[str, JsonValue]
    ) -> tuple[datetime, datetime | None, str, list[int], datetime | None] | ToolReceipt:
        try:
            start_at, inferred_recurrence, inferred_weekdays = self._parser.parse_schedule_start(str(arguments["start_text"]))
        except ValueError as exc:
            return self._input_error(arguments, "start_text", str(exc))
        recurrence = str(arguments.get("recurrence") or inferred_recurrence or "none")
        weekdays = list(arguments.get("weekdays") or inferred_weekdays or [])
        if recurrence == "weekly" and not weekdays:
            return self._input_error(arguments, "weekdays", "每周重复日程必须提供星期")
        if recurrence != "weekly":
            weekdays = []
        if len(set(weekdays)) != len(weekdays) or any(not isinstance(day, int) or day < 0 or day > 6 for day in weekdays):
            return self._input_error(arguments, "weekdays", "星期必须是不重复的 0 到 6 整数")

        end_at: datetime | None = None
        end_text = str(arguments.get("end_text", "")).strip()
        if not end_text:
            normalized_start_text = self._parser.normalize(str(arguments["start_text"]))
            interval = re.search(
                r"(?:到|至)\s*((?:上午|下午|晚上)?\s*\d{1,2}\s*(?::\s*\d{2}|点(?:半)?))",
                normalized_start_text,
            )
            end_text = interval.group(1) if interval else ""
        if end_text:
            try:
                end_at, _, _ = self._parser.parse_schedule_start(end_text, now=start_at)
            except ValueError:
                try:
                    hour, minute = self._parser.parse_time_of_day(end_text)
                    if (
                        hour < 12
                        and start_at.hour >= 12
                        and not any(marker in end_text for marker in ("上午", "下午", "晚上"))
                    ):
                        hour += 12
                    end_at = start_at.replace(hour=hour, minute=minute, second=0, microsecond=0)
                except ValueError as exc:
                    return self._input_error(arguments, "end_text", str(exc))
            if end_at <= start_at:
                return self._input_error(arguments, "end_text", "结束时间必须晚于开始时间")

        until_at: datetime | None = None
        if "recurrence_until_text" in arguments:
            try:
                until_at = self._parser.parse_date_boundary(str(arguments["recurrence_until_text"]), now=start_at)
            except ValueError as exc:
                return self._input_error(arguments, "recurrence_until_text", str(exc))
            if until_at < start_at:
                return self._input_error(arguments, "recurrence_until_text", "重复截止时间不能早于开始时间")
        return start_at, end_at, recurrence, weekdays, until_at

    async def _create(self, arguments: dict[str, JsonValue], owner: str) -> ToolReceipt:
        parsed = self._parse_create(arguments)
        if isinstance(parsed, ToolReceipt):
            return parsed
        start_at, end_at, recurrence, weekdays, until_at = parsed
        now = datetime.now(UTC).isoformat()
        async with self._lock:
            cursor = self._connection.execute(
                """INSERT INTO schedules(
                    title, location, start_at, end_at, recurrence, weekdays_json, recurrence_until_at,
                    status, notify_before_minutes, owner, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)""",
                (
                    str(arguments["title"]).strip(),
                    str(arguments.get("location", "")).strip(),
                    start_at.isoformat(),
                    end_at.isoformat() if end_at else None,
                    recurrence,
                    json.dumps(weekdays),
                    until_at.isoformat() if until_at else None,
                    int(arguments.get("notify_before_minutes", 15)),
                    owner,
                    now,
                ),
            )
            self._connection.commit()
            row = self._connection.execute("SELECT * FROM schedules WHERE id = ?", (cursor.lastrowid,)).fetchone()
        assert row is not None
        item = self._to_item(row)
        return ToolReceipt(
            tool_name=self.metadata.name,
            actual_arguments=arguments,
            success=True,
            output_summary=f"已创建日程 {item['id']}：{item['title']}",
            output={
                "item": item,
                "notice": "仅创建本地日程，不代表会议室已经锁定",
            },
        )

    def _range_window(self, arguments: dict[str, JsonValue], now: datetime) -> tuple[datetime, datetime]:
        local_now = now.astimezone(self._parser.timezone)
        day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        scope = str(arguments.get("range", "this_week"))
        if scope == "today":
            return day_start, day_start + timedelta(days=1)
        if scope == "tomorrow":
            return day_start + timedelta(days=1), day_start + timedelta(days=2)
        if scope == "this_week":
            start = day_start - timedelta(days=day_start.weekday())
            return start, start + timedelta(days=7)
        if scope == "next_week":
            start = day_start - timedelta(days=day_start.weekday()) + timedelta(days=7)
            return start, start + timedelta(days=7)
        if scope == "custom":
            start = datetime.fromisoformat(str(arguments["range_start"]))
            end = datetime.fromisoformat(str(arguments["range_end"]))
            if start.tzinfo is None:
                start = start.replace(tzinfo=self._parser.timezone)
            if end.tzinfo is None:
                end = end.replace(tzinfo=self._parser.timezone)
            if end <= start or end - start > timedelta(days=_MAX_RANGE_DAYS):
                raise ValueError("自定义查询范围必须大于 0 且不超过 31 天")
            return start, end
        raise ValueError("不支持的日程查询范围")

    @staticmethod
    def _occurrence(row: sqlite3.Row, start_at: datetime) -> dict[str, JsonValue]:
        base_start = datetime.fromisoformat(str(row["start_at"]))
        base_end = datetime.fromisoformat(str(row["end_at"])) if row["end_at"] else None
        duration = base_end - base_start if base_end else None
        end_at = start_at + duration if duration else None
        return {
            "schedule_id": int(row["id"]),
            "title": str(row["title"]),
            "location": str(row["location"]),
            "start_at": start_at.isoformat(),
            "end_at": end_at.isoformat() if end_at else None,
            "recurrence": str(row["recurrence"]),
            "notify_before_minutes": int(row["notify_before_minutes"]),
        }

    def _expand_row(self, row: sqlite3.Row, range_start: datetime, range_end: datetime) -> list[dict[str, JsonValue]]:
        base_start = datetime.fromisoformat(str(row["start_at"]))
        recurrence = str(row["recurrence"])
        until = datetime.fromisoformat(str(row["recurrence_until_at"])) if row["recurrence_until_at"] else None
        if recurrence == "none":
            return [self._occurrence(row, base_start)] if range_start <= base_start < range_end else []

        weekdays = set(json.loads(str(row["weekdays_json"])))
        cursor = max(base_start.date(), range_start.date())
        last_date = (range_end - timedelta(microseconds=1)).date()
        items: list[dict[str, JsonValue]] = []
        while cursor <= last_date:
            candidate = base_start.replace(year=cursor.year, month=cursor.month, day=cursor.day)
            allowed = (
                recurrence == "daily"
                or (recurrence == "weekly" and cursor.weekday() in weekdays)
                or (recurrence == "monthly" and cursor.day == base_start.day)
            )
            if allowed and candidate >= base_start and candidate >= range_start and candidate < range_end and (until is None or candidate <= until):
                items.append(self._occurrence(row, candidate))
            cursor += timedelta(days=1)
        return items

    async def _query(
        self, arguments: dict[str, JsonValue], owner: str = "", *, now: datetime | None = None
    ) -> ToolReceipt:
        current = now or datetime.now(self._parser.timezone)
        try:
            range_start, range_end = self._range_window(arguments, current)
        except (ValueError, KeyError) as exc:
            return self._input_error(arguments, "range", str(exc))
        title_query = str(arguments.get("title_query", "")).strip()
        sql = "SELECT * FROM schedules WHERE status = 'active' AND owner = ?"
        params: list[object] = [owner]
        if title_query:
            sql += " AND title LIKE ?"
            params.append(f"%{title_query}%")
        async with self._lock:
            rows = self._connection.execute(sql, tuple(params)).fetchall()
        occurrences: list[dict[str, JsonValue]] = []
        truncated = False
        # A title-only query is primarily used to select a record for cancel or
        # update. It must still find an active schedule outside the current week;
        # explicit range queries retain bounded occurrence expansion.
        title_candidate_mode = bool(title_query and "range" not in arguments)
        if title_candidate_mode:
            for row in rows[:_MAX_OCCURRENCES]:
                base_start = datetime.fromisoformat(str(row["start_at"]))
                occurrences.append(self._occurrence(row, base_start))
            truncated = len(rows) > _MAX_OCCURRENCES
        else:
            for row in rows:
                for occurrence in self._expand_row(row, range_start, range_end):
                    if len(occurrences) >= _MAX_OCCURRENCES:
                        truncated = True
                        break
                    occurrences.append(occurrence)
                if truncated:
                    break
        occurrences.sort(key=lambda item: (str(item["start_at"]), int(item["schedule_id"])))
        return ToolReceipt(
            tool_name=self.metadata.name,
            actual_arguments=arguments,
            success=True,
            output_summary=f"查询到 {len(occurrences)} 个日程实例" + ("，结果已截断" if truncated else ""),
            output={
                "items": occurrences,
                "range_start": range_start.isoformat(),
                "range_end": range_end.isoformat(),
                "truncated": truncated,
                "candidate_mode": title_candidate_mode,
            },
        )

    async def query(self, arguments: dict[str, JsonValue], *, now: datetime, owner: str = "") -> ToolReceipt:
        """Expose a fixed-clock query surface for deterministic tests and polling."""

        return await self._query(arguments, owner, now=now)

    async def _cancel(self, schedule_id: int, arguments: dict[str, JsonValue], owner: str) -> ToolReceipt:
        now = datetime.now(UTC).isoformat()
        async with self._lock:
            row = self._connection.execute(
                "SELECT * FROM schedules WHERE id = ? AND owner = ?", (schedule_id, owner)
            ).fetchone()
            if row is None:
                return ToolReceipt(
                    tool_name=self.metadata.name,
                    actual_arguments=arguments,
                    success=True,
                    output_summary=f"未找到日程 {schedule_id}",
                    output={"updated": False, "id": schedule_id},
                )
            if row["status"] == "cancelled":
                return ToolReceipt(
                    tool_name=self.metadata.name,
                    actual_arguments=arguments,
                    success=True,
                    output_summary=f"日程 {schedule_id} 已取消",
                    output={"updated": False, "item": self._to_item(row)},
                )
            self._connection.execute(
                "UPDATE schedules SET status = 'cancelled', cancelled_at = ? WHERE id = ? AND owner = ?",
                (now, schedule_id, owner),
            )
            self._connection.commit()
            cancelled = self._connection.execute(
                "SELECT * FROM schedules WHERE id = ? AND owner = ?", (schedule_id, owner)
            ).fetchone()
        assert cancelled is not None
        return ToolReceipt(
            tool_name=self.metadata.name,
            actual_arguments=arguments,
            success=True,
            output_summary=f"已取消日程 {schedule_id}",
            output={"item": self._to_item(cancelled)},
        )

    async def confirmation_context(
        self, arguments: dict[str, JsonValue], context: ToolContext | None = None
    ) -> dict[str, str]:
        """Return read-only facts for a pre-execution cancellation confirmation."""

        if arguments.get("action") != "cancel" or not isinstance(arguments.get("id"), int):
            return {}
        try:
            owner = self._required_owner(context)
        except ValueError:
            return {}
        async with self._lock:
            row = self._connection.execute(
                "SELECT title, start_at FROM schedules WHERE id = ? AND owner = ?",
                (int(arguments["id"]), owner),
            ).fetchone()
        if row is None:
            return {}
        return {"title": str(row["title"]), "start_at": str(row["start_at"])}

    async def poll_due(self, *, now: datetime | None = None) -> int:
        """Record notification keys transactionally before emitting each local notification."""

        current = now or datetime.now(self._parser.timezone)
        window_start = current - timedelta(minutes=1)
        window_end = current + timedelta(days=1, minutes=1)
        to_notify: list[dict[str, JsonValue]] = []
        async with self._lock:
            rows = self._connection.execute("SELECT * FROM schedules WHERE status = 'active'").fetchall()
            for row in rows:
                for occurrence in self._expand_row(row, window_start, window_end):
                    start_at = datetime.fromisoformat(str(occurrence["start_at"]))
                    notify_at = start_at - timedelta(minutes=int(occurrence["notify_before_minutes"]))
                    if notify_at > current:
                        continue
                    cursor = self._connection.execute(
                        """INSERT OR IGNORE INTO schedule_notifications(schedule_id, occurrence_start_at, notified_at)
                        VALUES (?, ?, ?)""",
                        (int(occurrence["schedule_id"]), str(occurrence["start_at"]), datetime.now(UTC).isoformat()),
                    )
                    if cursor.rowcount == 1:
                        to_notify.append({**occurrence, "text": occurrence["title"]})
            self._connection.commit()
        for occurrence in to_notify:
            await self._callback(occurrence)
        return len(to_notify)

    async def start_scheduler(self) -> None:
        if self._scheduler_task is None:
            self._scheduler_task = asyncio.create_task(self._scheduler_loop())

    async def stop_scheduler(self) -> None:
        if self._scheduler_task is not None:
            self._scheduler_task.cancel()
            await asyncio.gather(self._scheduler_task, return_exceptions=True)
            self._scheduler_task = None

    async def _scheduler_loop(self) -> None:
        while True:
            try:
                await self.poll_due()
            except asyncio.CancelledError:
                raise
            except Exception:
                # Same supervision gap as the reminder loop: an unhandled poll
                # error would silently disable all later schedule notifications.
                logger.exception("schedule scheduler poll failed; continuing loop")
            await asyncio.sleep(0.5)

    async def _log_callback(self, occurrence: dict[str, JsonValue]) -> None:
        print(f"SCHEDULE: {occurrence.get('title', '')}")

    def close(self) -> None:
        self._connection.close()


__all__ = ["ScheduleTool"]
