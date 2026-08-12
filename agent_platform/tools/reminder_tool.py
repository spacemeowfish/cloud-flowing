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

# Keep the stored reminder body separate from the natural-language command that
# created it.  The same cleanup is applied to legacy rows when they are read so
# an existing database does not keep displaying the command prefix.
_REMINDER_COMMAND_PREFIX = re.compile(
    r"^\s*(?:请|帮我|请帮我)?(?:提醒我|提醒|设置提醒|创建提醒)[：:\s]*"
)
_CN_TIME_NUMBER = r"[0-9零〇一二两三四五六七八九十百千万壹贰叁肆伍陆柒捌玖拾佰仟萬億]+"
_REMINDER_TIME_PREFIX = re.compile(
    rf"^\s*(?:"
    rf"{_CN_TIME_NUMBER}\s*(?:分钟|小时|天)后"
    rf"|(?:今天|明天|后天)(?:(?:上午|下午|晚上)\s*)?"
    rf"{_CN_TIME_NUMBER}(?::\s*\d{{2}}|点(?:半)?)"
    rf"|每周[一二三四五六日天壹贰叁肆伍陆柒捌玖]+(?:(?:上午|下午|晚上)\s*)?"
    rf"{_CN_TIME_NUMBER}(?::\s*\d{{2}}|点(?:半)?)"
    rf")\s*(?:提醒我|提醒)?[：:\s]*"
)
_REMINDER_TIME_SUFFIX = re.compile(
    rf"[，,、\s]*(?:{_CN_TIME_NUMBER}\s*(?:分钟|小时|天)后|"
    rf"(?:今天|明天|后天)(?:(?:上午|下午|晚上)\s*)?{_CN_TIME_NUMBER}(?::\s*\d{{2}}|点(?:半)?)|"
    rf"每周[一二三四五六日天壹贰叁肆伍陆柒捌玖]+(?:(?:上午|下午|晚上)\s*)?{_CN_TIME_NUMBER}(?::\s*\d{{2}}|点(?:半)?))\s*$"
)


def clean_reminder_text(raw_text: str) -> str:
    """Return the user-facing reminder body without command/time boilerplate."""

    original = str(raw_text or "").strip()
    if not original:
        return original
    cleaned = _REMINDER_COMMAND_PREFIX.sub("", original, count=1)
    # Accept both ``提醒我 5 分钟后开会`` and ``5 分钟后提醒我开会``.
    cleaned = _REMINDER_TIME_PREFIX.sub("", cleaned, count=1)
    cleaned = _REMINDER_COMMAND_PREFIX.sub("", cleaned, count=1)
    cleaned = _REMINDER_TIME_SUFFIX.sub("", cleaned, count=1)
    return cleaned.strip() or original


class ChineseTimeParser:
    # Both everyday and financial/uppercase Chinese numerals occur in spoken
    # schedule input.  Parsing a complete number token avoids the old ``十五``
    # -> ``105`` replacement bug.
    _CN_DIGITS = {
        "零": 0,
        "〇": 0,
        "○": 0,
        "一": 1,
        "壹": 1,
        "二": 2,
        "贰": 2,
        "两": 2,
        "俩": 2,
        "三": 3,
        "叁": 3,
        "四": 4,
        "肆": 4,
        "五": 5,
        "伍": 5,
        "六": 6,
        "陆": 6,
        "七": 7,
        "柒": 7,
        "八": 8,
        "捌": 8,
        "九": 9,
        "玖": 9,
    }
    _CN_UNITS = {
        "十": 10,
        "拾": 10,
        "百": 100,
        "佰": 100,
        "千": 1000,
        "仟": 1000,
        "万": 10000,
        "萬": 10000,
        "亿": 100000000,
        "億": 100000000,
    }
    _CN_NUMBER_TOKEN = re.compile(
        r"[零〇○一二两俩三四五六七八九十百千万亿壹贰叁肆伍陆柒捌玖拾佰仟萬億]+"
    )

    def __init__(self, timezone: str = "Asia/Shanghai") -> None:
        self.timezone = ZoneInfo(timezone)

    def normalize(self, text: str) -> str:
        """Normalize Chinese numeric tokens to Arabic digits for regex parsing."""

        def replace(match: re.Match[str]) -> str:
            token = match.group(0)
            # A token without a unit is a digit sequence (e.g. 二〇二六 -> 2026).
            if not any(char in self._CN_UNITS for char in token):
                return "".join(str(self._CN_DIGITS[char]) for char in token)
            section = 0
            total = 0
            number = 0
            for char in token:
                digit = self._CN_DIGITS.get(char)
                if digit is not None:
                    number = number * 10 + digit
                    continue
                unit = self._CN_UNITS[char]
                if unit < 10000:
                    section += (number or 1) * unit
                    number = 0
                else:
                    section += number
                    total += (section or 1) * unit
                    section = 0
                    number = 0
            return str(total + section + number)

        return self._CN_NUMBER_TOKEN.sub(replace, text)

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

        weekly = re.search(r"每周([一二三四五六日天])", text)
        if weekly:
            weekday = _WEEKDAYS[weekly.group(1)]
            hour, minute = self.parse_time_of_day(text)
            if "下午" in normalized and hour < 12:
                hour += 12
            days = (weekday - current.weekday()) % 7
            candidate = (current + timedelta(days=days)).replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate <= current:
                candidate += timedelta(days=7)
            return candidate, f"weekly:{weekday}:{hour:02d}:{minute:02d}"

        iso = re.search(
            r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})日?\s*"
            r"(上午|下午|晚上)?\s*(\d{1,2})(?::(\d{2})|点(?:半)?)?",
            normalized,
        )
        if iso:
            period = iso.group(4) or ""
            hour = int(iso.group(5))
            minute = 30 if iso.group(6) is None and "点半" in iso.group(0) else int(iso.group(6) or 0)
            if period in {"下午", "晚上"} and hour < 12:
                hour += 12
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
        if arguments.get("action") == "query":
            # Query results are mutable.  A stable key would replay the first
            # result for the whole executor TTL after a create/delete action.
            return f"reminder:query:{datetime.now(UTC).isoformat()}"
        value = json.dumps(arguments, ensure_ascii=False, sort_keys=True)
        return f"reminder:{hashlib.sha256(value.encode()).hexdigest()}"

    @staticmethod
    def _item(row: sqlite3.Row | dict[str, JsonValue]) -> dict[str, JsonValue]:
        """Return a stable, human-readable reminder representation."""

        get = row.__getitem__
        return {
            "id": int(get("id")),
            "text": clean_reminder_text(str(get("text"))),
            "due_at": str(get("due_at")),
            "repeat_rule": str(get("repeat_rule")) if get("repeat_rule") is not None else None,
            "status": str(get("status")),
            "created_at": str(get("created_at")),
        }

    async def execute(self, arguments: dict[str, JsonValue]) -> ToolReceipt:
        action = str(arguments["action"])
        if action == "create":
            raw_text = str(arguments.get("text", ""))
            text = clean_reminder_text(raw_text)
            when = str(arguments.get("when", "")).strip()
            if not text and when:
                text = clean_reminder_text(when)
            # Parse the original request so an embedded time such as
            # ``30分钟后检查服务`` is not removed before the time parser sees it.
            expression = f"{raw_text} {when}".strip() if when else raw_text.strip()
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
            row = self._connection.execute("SELECT * FROM reminders WHERE id = ?", (cursor.lastrowid,)).fetchone()
            assert row is not None
            item = self._item(row)
            output = {"id": cursor.lastrowid, "item": item, "due_at": due_at.isoformat(), "repeat_rule": repeat_rule, "status": "active"}
            summary = f"已创建提醒 {item['id']}：{item['text']}（{due_at.isoformat()}）"
        elif action in {"cancel", "complete"}:
            reminder_id = int(arguments.get("id", 0))
            status = "cancelled" if action == "cancel" else "completed"
            existing = self._connection.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
            if existing is None:
                self._connection.commit()
                output = {"id": reminder_id, "status": status, "updated": False, "item": None}
                summary = f"未找到提醒 {reminder_id}"
                return ToolReceipt(
                    tool_name=self.metadata.name,
                    actual_arguments=arguments,
                    success=True,
                    output_summary=summary,
                    output=output,
                )
            cursor = self._connection.execute("UPDATE reminders SET status = ? WHERE id = ?", (status, reminder_id))
            self._connection.commit()
            updated = self._connection.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
            assert updated is not None
            item = self._item(updated)
            output = {"id": reminder_id, "status": status, "updated": cursor.rowcount == 1, "item": item}
            verb = "已取消" if action == "cancel" else "已完成"
            summary = f"提醒 {reminder_id} {verb}：{item['text']}（{item['due_at']}）"
        elif action == "delete_all":
            rows = self._connection.execute("SELECT * FROM reminders ORDER BY due_at, id").fetchall()
            cursor = self._connection.execute("DELETE FROM reminders")
            self._connection.commit()
            deleted_items = [self._item(row) for row in rows]
            output = {"deleted_count": cursor.rowcount, "deleted_items": deleted_items, "status": "deleted"}
            summary = f"已删除 {cursor.rowcount} 条提醒" + (
                "：" + "；".join(f"{item['id']} {item['text']}" for item in deleted_items) if deleted_items else ""
            )
        elif action == "query":
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
        return [self._item(row) for row in rows]

    async def poll_due(self, *, now: datetime | None = None) -> int:
        current = now or datetime.now(self._parser.timezone)
        rows = self._connection.execute(
            "SELECT * FROM reminders WHERE status = 'active' AND due_at <= ? ORDER BY due_at", (current.isoformat(),)
        ).fetchall()
        for row in rows:
            await self._callback(self._item(row))
            if row["repeat_rule"]:
                _, weekday, hour, minute = str(row["repeat_rule"]).split(":")
                due = datetime.fromisoformat(row["due_at"]) + timedelta(days=7)
                self._connection.execute("UPDATE reminders SET due_at = ? WHERE id = ?", (due.isoformat(), row["id"]))
            else:
                self._connection.execute("UPDATE reminders SET status = 'notified' WHERE id = ?", (row["id"],))
        self._connection.commit()
        return len(rows)

    async def confirmation_context(self, arguments: dict[str, JsonValue]) -> dict[str, str]:
        """Expose the selected reminder body to a confirmation UI."""

        if arguments.get("action") not in {"cancel", "complete"} or not isinstance(arguments.get("id"), int):
            return {}
        row = self._connection.execute("SELECT * FROM reminders WHERE id = ?", (int(arguments["id"]),)).fetchone()
        if row is None:
            return {}
        item = self._item(row)
        return {"text": str(item["text"]), "due_at": str(item["due_at"]), "status": str(item["status"])}

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


__all__ = ["ChineseTimeParser", "ReminderTool", "clean_reminder_text"]
