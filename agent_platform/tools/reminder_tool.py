"""Chinese-first reminder parsing, persistence, querying, and scheduling."""

import asyncio
import calendar
import hashlib
import json
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Awaitable, Callable
from zoneinfo import ZoneInfo

from pydantic import JsonValue

from agent_platform.core.interfaces import Tool
from agent_platform.models import DataLevel, RiskLevel, ToolMetadata, ToolReceipt


_WEEKDAYS = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}


class ChineseTimeParser:
    _CN_DIGITS = {"一": "1", "二": "2", "两": "2", "三": "3", "四": "4",
                  "五": "5", "六": "6", "七": "7", "八": "8", "九": "9",
                  "半": "0.5"}

    _CN_TENS: dict[str, str] = {"十": "10"}
    _CN_COMPOUND: list[tuple[str, str]] = [
        ("二十", "20"), ("三十", "30"), ("四十", "40"), ("五十", "50"),
        ("六十", "60"), ("七十", "70"), ("八十", "80"), ("九十", "90"),
    ]

    def __init__(self, timezone: str = "Asia/Shanghai") -> None:
        self.timezone = ZoneInfo(timezone)

    def normalize(self, text: str) -> str:
        """Normalize the limited Chinese numerals accepted by local time parsing."""

        normalized = text
        for cn, digit in self._CN_COMPOUND:
            normalized = normalized.replace(cn, digit)
        for cn, digit in self._CN_TENS.items():
            normalized = normalized.replace(cn, digit)
        for cn, digit in self._CN_DIGITS.items():
            normalized = normalized.replace(cn, digit)
        return normalized

    def parse_time_of_day(self, text: str) -> tuple[int, int]:
        """Parse an explicit clock time without assigning a date."""

        normalized = self.normalize(text)
        match = re.search(r"(\d{1,2})\s*(?::\s*(\d{2})|点(?:半)?)", normalized)
        if match is None:
            raise ValueError("无法解析具体时刻")
        hour = int(match.group(1))
        minute = 30 if "点半" in match.group(0) else int(match.group(2) or 0)
        if any(marker in normalized for marker in ("下午", "晚上")) and hour < 12:
            hour += 12
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            raise ValueError("时间超出有效范围")
        return hour, minute

    def parse_schedule_start(
        self, text: str, *, now: datetime | None = None
    ) -> tuple[datetime, str | None, list[int] | None]:
        """Parse schedule-specific recurrence expressions using the shared timezone rules."""

        normalized = self.normalize(text)
        current = now or datetime.now(self.timezone)
        if current.tzinfo is None:
            current = current.replace(tzinfo=self.timezone)
        hour, minute = self.parse_time_of_day(normalized)

        if "每天" in normalized or "每日" in normalized:
            candidate = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate <= current:
                candidate += timedelta(days=1)
            return candidate, "daily", None

        weekly = re.search(r"每周([一二三四五六日天]+)", text)
        if weekly:
            weekdays = list(dict.fromkeys(_WEEKDAYS[char] for char in weekly.group(1)))
            candidates = [
                (current + timedelta(days=(weekday - current.weekday()) % 7)).replace(
                    hour=hour, minute=minute, second=0, microsecond=0
                )
                for weekday in weekdays
            ]
            candidate = min(item + timedelta(days=7) if item <= current else item for item in candidates)
            return candidate, "weekly", weekdays

        monthly = re.search(r"每月(\d{1,2})日", normalized)
        if monthly:
            day = int(monthly.group(1))
            if not 1 <= day <= 31:
                raise ValueError("每月日期超出有效范围")
            year, month = current.year, current.month
            while day > calendar.monthrange(year, month)[1]:
                month = 1 if month == 12 else month + 1
                year += month == 1
            candidate = datetime(year, month, day, hour, minute, tzinfo=self.timezone)
            if candidate <= current:
                month = 1 if month == 12 else month + 1
                year += month == 1
                while day > calendar.monthrange(year, month)[1]:
                    month = 1 if month == 12 else month + 1
                    year += month == 1
                candidate = datetime(year, month, day, hour, minute, tzinfo=self.timezone)
            return candidate, "monthly", None

        due_at, _ = self.parse(text, now=current)
        return due_at, None, None

    def parse_date_boundary(self, text: str, *, now: datetime | None = None) -> datetime:
        """Parse an explicit date as its local end-of-day recurrence boundary."""

        normalized = self.normalize(text)
        match = re.search(r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})日?", normalized)
        if match:
            return datetime(
                int(match.group(1)), int(match.group(2)), int(match.group(3)), 23, 59, 59, tzinfo=self.timezone
            )
        due_at, _ = self.parse(text, now=now)
        return due_at

    def parse(self, text: str, *, now: datetime | None = None) -> tuple[datetime, str | None]:
        # Normalize Chinese numerals to Arabic digits: 十五分钟 → 15分钟
        normalized = self.normalize(text)

        current = now or datetime.now(self.timezone)
        if current.tzinfo is None:
            current = current.replace(tzinfo=self.timezone)

        relative = re.search(r"(\d+)\s*(分钟|小时|天)后", normalized)
        if relative:
            value = int(relative.group(1))
            unit = relative.group(2)
            delta = {"分钟": timedelta(minutes=value), "小时": timedelta(hours=value), "天": timedelta(days=value)}[unit]
            return current + delta, None

        weekly = re.search(r"每周([一二三四五六日天]).*?(\d{1,2})(?::(\d{2})|点)", text)
        if weekly:
            weekday = _WEEKDAYS[weekly.group(1)]
            hour = int(weekly.group(2))
            minute = int(weekly.group(3) or 0)
            if "下午" in normalized and hour < 12:
                hour += 12
            days = (weekday - current.weekday()) % 7
            candidate = (current + timedelta(days=days)).replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate <= current:
                candidate += timedelta(days=7)
            return candidate, f"weekly:{weekday}:{hour:02d}:{minute:02d}"

        iso = re.search(r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})日?\s*(\d{1,2})(?::(\d{2})|点)?", normalized)
        if iso:
            hour = int(iso.group(4))
            minute = int(iso.group(5) or 0)
            return datetime(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)), hour, minute, tzinfo=self.timezone), None

        day_offset = 0
        if "后天" in normalized:
            day_offset = 2
        elif "明天" in normalized:
            day_offset = 1
        elif "今天" in normalized:
            day_offset = 0
        time_match = re.search(r"(\d{1,2})(?::(\d{2})|点(?:半)?)", normalized)
        if time_match and any(marker in normalized for marker in ("今天", "明天", "后天", "上午", "下午", "晚上")):
            hour = int(time_match.group(1))
            minute = 30 if "点半" in time_match.group(0) else int(time_match.group(2) or 0)
            if any(marker in normalized for marker in ("下午", "晚上")) and hour < 12:
                hour += 12
            candidate = (current + timedelta(days=day_offset)).replace(hour=hour, minute=minute, second=0, microsecond=0)
            if day_offset == 0 and candidate <= current:
                candidate += timedelta(days=1)
            return candidate, None
        raise ValueError("无法解析提醒时间，请提供如‘明天下午3点’或‘30分钟后’")


class ReminderTool(Tool):
    def __init__(
        self,
        database_path: Path,
        timezone: str = "Asia/Shanghai",
        callback: Callable[[dict[str, JsonValue]], Awaitable[None]] | None = None,
    ) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(database_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute(
            """CREATE TABLE IF NOT EXISTS reminders(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                due_at TEXT NOT NULL,
                repeat_rule TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL
            )"""
        )
        self._connection.commit()
        self._parser = ChineseTimeParser(timezone)
        self._callback = callback or self._log_callback
        self._scheduler_task: asyncio.Task[None] | None = None

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="reminder_create",
            description="Create, query, cancel, and complete local reminders",
            parameters_schema={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["create", "query", "cancel", "complete", "delete_all"]},
                    "text": {"type": "string"},
                    "when": {"type": "string"},
                    "id": {"type": "integer", "minimum": 1},
                    "scope": {"type": "string", "enum": ["next_7_days", "overdue"]},
                },
                "required": ["action"],
                "allOf": [
                    {
                        "if": {"properties": {"action": {"const": "cancel"}}, "required": ["action"]},
                        "then": {"required": ["id"]},
                    },
                    {
                        "if": {"properties": {"action": {"const": "complete"}}, "required": ["action"]},
                        "then": {"required": ["id"]},
                    },
                ],
                "additionalProperties": False,
            },
            risk_level=RiskLevel.R1,
            data_level=DataLevel.D1,
            timeout_seconds=5,
        )

    def idempotency_key(self, arguments: dict[str, JsonValue]) -> str:
        value = json.dumps(arguments, ensure_ascii=False, sort_keys=True)
        return f"reminder:{hashlib.sha256(value.encode()).hexdigest()}"

    async def execute(self, arguments: dict[str, JsonValue]) -> ToolReceipt:
        action = str(arguments["action"])
        if action == "create":
            text = str(arguments.get("text", ""))
            when = str(arguments.get("when", "")).strip()
            expression = f"{text} {when}".strip() if when else text
            try:
                due_at, repeat_rule = self._parser.parse(expression)
            except ValueError as exc:
                return ToolReceipt(
                    tool_name=self.metadata.name,
                    actual_arguments=arguments,
                    success=True,
                    output_summary=str(exc),
                    output={
                        "requires_confirmation": True,
                        "confirmation_type": "missing_fields",
                        "fields": ["when"],
                        "message": str(exc),
                    },
                    next_actions=["补充具体时间后重试"],
                )
            cursor = self._connection.execute(
                "INSERT INTO reminders(text, due_at, repeat_rule, status, created_at) VALUES (?, ?, ?, 'active', ?)",
                (text, due_at.isoformat(), repeat_rule, datetime.now(UTC).isoformat()),
            )
            self._connection.commit()
            output = {"id": cursor.lastrowid, "due_at": due_at.isoformat(), "repeat_rule": repeat_rule, "status": "active"}
            summary = f"已创建提醒，时间：{due_at.isoformat()}"
        elif action in {"cancel", "complete"}:
            reminder_id = int(arguments.get("id", 0))
            status = "cancelled" if action == "cancel" else "completed"
            cursor = self._connection.execute("UPDATE reminders SET status = ? WHERE id = ?", (status, reminder_id))
            self._connection.commit()
            output = {"id": reminder_id, "status": status, "updated": cursor.rowcount == 1}
            summary = f"提醒 {reminder_id} 状态已更新为 {status}"
        elif action == "delete_all":
            cursor = self._connection.execute("DELETE FROM reminders")
            self._connection.commit()
            output = {"deleted_count": cursor.rowcount, "status": "deleted"}
            summary = f"已删除 {cursor.rowcount} 条提醒"
        else:
            output = {"items": self.query(str(arguments.get("scope", "next_7_days")))}
            summary = f"查询到 {len(output['items'])} 条提醒"
        return ToolReceipt(
            tool_name=self.metadata.name,
            actual_arguments=arguments,
            success=True,
            output_summary=summary,
            output=output,
        )

    def query(self, scope: str = "next_7_days", *, now: datetime | None = None) -> list[dict[str, JsonValue]]:
        current = now or datetime.now(self._parser.timezone)
        if scope == "overdue":
            rows = self._connection.execute(
                "SELECT * FROM reminders WHERE status IN ('active', 'notified') AND due_at < ? ORDER BY due_at",
                (current.isoformat(),),
            ).fetchall()
        else:
            end = current + timedelta(days=7)
            rows = self._connection.execute(
                "SELECT * FROM reminders WHERE status IN ('active', 'notified') AND due_at BETWEEN ? AND ? ORDER BY due_at",
                (current.isoformat(), end.isoformat()),
            ).fetchall()
        return [dict(row) for row in rows]  # type: ignore[return-value]

    async def poll_due(self, *, now: datetime | None = None) -> int:
        current = now or datetime.now(self._parser.timezone)
        rows = self._connection.execute(
            "SELECT * FROM reminders WHERE status = 'active' AND due_at <= ? ORDER BY due_at", (current.isoformat(),)
        ).fetchall()
        for row in rows:
            await self._callback(dict(row))  # type: ignore[arg-type]
            if row["repeat_rule"]:
                _, weekday, hour, minute = str(row["repeat_rule"]).split(":")
                due = datetime.fromisoformat(row["due_at"]) + timedelta(days=7)
                self._connection.execute("UPDATE reminders SET due_at = ? WHERE id = ?", (due.isoformat(), row["id"]))
            else:
                self._connection.execute("UPDATE reminders SET status = 'notified' WHERE id = ?", (row["id"],))
        self._connection.commit()
        return len(rows)

    async def start_scheduler(self) -> None:
        if self._scheduler_task is None:
            self._scheduler_task = asyncio.create_task(self._scheduler_loop())

    async def stop_scheduler(self) -> None:
        if self._scheduler_task:
            self._scheduler_task.cancel()
            await asyncio.gather(self._scheduler_task, return_exceptions=True)
            self._scheduler_task = None

    async def _scheduler_loop(self) -> None:
        while True:
            await self.poll_due()
            await asyncio.sleep(0.5)

    async def _log_callback(self, reminder: dict[str, JsonValue]) -> None:
        print(f"REMINDER: {reminder.get('text', '')}")

    def close(self) -> None:
        self._connection.close()


__all__ = ["ChineseTimeParser", "ReminderTool"]
