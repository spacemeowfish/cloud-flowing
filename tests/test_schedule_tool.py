from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from agent_platform.core.errors import SchemaValidationError
from agent_platform.core.schema_validator import SchemaValidator
from agent_platform.tools.schedule_tool import ScheduleTool

from agent_platform.models import ToolContext

CTX = ToolContext(owner="default")
OWNER = "default"


TZ = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 7, 28, 10, 0, tzinfo=TZ)


def _clocked(tool: ScheduleTool, monkeypatch) -> None:
    original = tool._parser.parse_schedule_start

    def parse_with_fixed_clock(text: str, *, now: datetime | None = None):
        return original(text, now=NOW if now is None else now)

    monkeypatch.setattr(tool._parser, "parse_schedule_start", parse_with_fixed_clock)


def _custom(start: datetime, end: datetime) -> dict[str, str]:
    return {"range": "custom", "range_start": start.isoformat(), "range_end": end.isoformat()}


@pytest.mark.asyncio
async def test_schedule_creates_one_time_interval_from_chinese_text(tmp_path, monkeypatch):
    tool = ScheduleTool(tmp_path / "schedules.db")
    _clocked(tool, monkeypatch)
    receipt = await tool.execute(
        {"action": "create", "title": "项目会议", "start_text": "明天下午2点到4点", "location": "会议室A"}
    , context=CTX)
    item = receipt.output["item"]
    assert item["start_at"] == datetime(2026, 7, 29, 14, 0, tzinfo=TZ).isoformat()
    assert item["end_at"] == datetime(2026, 7, 29, 16, 0, tzinfo=TZ).isoformat()
    assert item["notify_before_minutes"] == 15
    tool.close()


@pytest.mark.asyncio
async def test_schedule_invalid_time_and_reversed_end_do_not_write(tmp_path, monkeypatch):
    tool = ScheduleTool(tmp_path / "schedules.db")
    _clocked(tool, monkeypatch)
    invalid = await tool.execute({"action": "create", "title": "不完整", "start_text": "下周开会"}, context=CTX)
    assert invalid.output["requires_confirmation"] is True
    reversed_time = await tool.execute(
        {"action": "create", "title": "倒置", "start_text": "明天下午2点", "end_text": "1点"}
    , context=CTX)
    assert reversed_time.output["fields"] == ["end_text"]
    assert tool._connection.execute("SELECT count(*) FROM schedules").fetchone()[0] == 0
    tool.close()


def test_schedule_schema_requires_create_cancel_weekdays_and_custom_bounds(tmp_path):
    tool = ScheduleTool(tmp_path / "schedules.db")
    with pytest.raises(SchemaValidationError):
        SchemaValidator.validate({"action": "create", "title": "x"}, tool.metadata.parameters_schema)
    with pytest.raises(SchemaValidationError):
        SchemaValidator.validate({"action": "cancel"}, tool.metadata.parameters_schema)
    with pytest.raises(SchemaValidationError):
        SchemaValidator.validate(
            {"action": "create", "title": "x", "start_text": "每周一上午9点", "recurrence": "weekly"},
            tool.metadata.parameters_schema,
        )
    with pytest.raises(SchemaValidationError):
        SchemaValidator.validate({"action": "query", "range": "custom"}, tool.metadata.parameters_schema)
    tool.close()


@pytest.mark.asyncio
async def test_schedule_persists_after_reopen(tmp_path):
    path = tmp_path / "schedules.db"
    tool = ScheduleTool(path)
    created = await tool.execute({"action": "create", "title": "持久化", "start_text": "2026-07-28 14:00"}, context=CTX)
    schedule_id = created.output["item"]["id"]
    tool.close()
    reopened = ScheduleTool(path)
    queried = await reopened.query({"action": "query", **_custom(NOW, NOW + timedelta(days=1))}, now=NOW, owner=OWNER)
    assert queried.output["items"][0]["schedule_id"] == schedule_id
    reopened.close()


@pytest.mark.asyncio
async def test_schedule_daily_recurrence_is_bounded_to_query_range(tmp_path, monkeypatch):
    tool = ScheduleTool(tmp_path / "schedules.db")
    _clocked(tool, monkeypatch)
    await tool.execute({"action": "create", "title": "日报", "start_text": "每天下午3点", "recurrence": "daily"}, context=CTX)
    queried = await tool.query({"action": "query", **_custom(NOW, NOW + timedelta(days=4))}, now=NOW, owner=OWNER)
    assert len(queried.output["items"]) == 4
    assert all(item["recurrence"] == "daily" for item in queried.output["items"])
    tool.close()


@pytest.mark.asyncio
async def test_schedule_weekly_multiple_weekdays_expand_correctly(tmp_path, monkeypatch):
    tool = ScheduleTool(tmp_path / "schedules.db")
    _clocked(tool, monkeypatch)
    await tool.execute(
        {"action": "create", "title": "站会", "start_text": "每周一三五上午9点", "recurrence": "weekly", "weekdays": [0, 2, 4]}
    , context=CTX)
    queried = await tool.query({"action": "query", **_custom(NOW, NOW + timedelta(days=14))}, now=NOW, owner=OWNER)
    assert len(queried.output["items"]) == 6
    assert {datetime.fromisoformat(item["start_at"]).weekday() for item in queried.output["items"]} == {0, 2, 4}
    tool.close()


@pytest.mark.asyncio
async def test_schedule_monthly_uses_original_day_and_skips_invalid_month_days(tmp_path, monkeypatch):
    tool = ScheduleTool(tmp_path / "schedules.db")
    _clocked(tool, monkeypatch)
    await tool.execute({"action": "create", "title": "月度", "start_text": "每月31日 10点", "recurrence": "monthly"}, context=CTX)
    start = datetime(2026, 8, 1, tzinfo=TZ)
    end = datetime(2026, 9, 1, tzinfo=TZ)
    queried = await tool.query({"action": "query", **_custom(start, end)}, now=NOW, owner=OWNER)
    assert [datetime.fromisoformat(item["start_at"]).day for item in queried.output["items"]] == [31]
    tool.close()


@pytest.mark.asyncio
async def test_schedule_recurrence_until_is_an_inclusive_upper_boundary(tmp_path, monkeypatch):
    tool = ScheduleTool(tmp_path / "schedules.db")
    _clocked(tool, monkeypatch)
    await tool.execute(
        {
            "action": "create",
            "title": "截止日报",
            "start_text": "每天下午3点",
            "recurrence": "daily",
            "recurrence_until_text": "2026-07-30",
        }
    , context=CTX)
    queried = await tool.query({"action": "query", **_custom(NOW, NOW + timedelta(days=5))}, now=NOW, owner=OWNER)
    assert len(queried.output["items"]) == 3
    tool.close()


@pytest.mark.asyncio
async def test_schedule_named_ranges_today_tomorrow_and_weeks(tmp_path):
    tool = ScheduleTool(tmp_path / "schedules.db")
    await tool.execute({"action": "create", "title": "今天", "start_text": "2026-07-28 14:00"}, context=CTX)
    await tool.execute({"action": "create", "title": "明天", "start_text": "2026-07-29 14:00"}, context=CTX)
    today = await tool.query({"action": "query", "range": "today"}, now=NOW, owner=OWNER)
    tomorrow = await tool.query({"action": "query", "range": "tomorrow"}, now=NOW, owner=OWNER)
    this_week = await tool.query({"action": "query", "range": "this_week"}, now=NOW, owner=OWNER)
    next_week = await tool.query({"action": "query", "range": "next_week"}, now=NOW, owner=OWNER)
    assert len(today.output["items"]) == 1
    assert len(tomorrow.output["items"]) == 1
    assert len(this_week.output["items"]) == 2
    assert next_week.output["items"] == []
    tool.close()


@pytest.mark.asyncio
async def test_schedule_rejects_custom_ranges_over_31_days_without_side_effect(tmp_path):
    tool = ScheduleTool(tmp_path / "schedules.db")
    result = await tool.query({"action": "query", **_custom(NOW, NOW + timedelta(days=32))}, now=NOW, owner=OWNER)
    assert result.output["requires_confirmation"] is True
    assert result.output["fields"] == ["range"]
    tool.close()


@pytest.mark.asyncio
async def test_schedule_cancel_marks_only_target_and_unknown_id_is_safe(tmp_path):
    tool = ScheduleTool(tmp_path / "schedules.db")
    first = await tool.execute({"action": "create", "title": "同名", "start_text": "2026-07-28 14:00"}, context=CTX)
    second = await tool.execute({"action": "create", "title": "同名", "start_text": "2026-07-29 14:00"}, context=CTX)
    first_id = first.output["item"]["id"]
    second_id = second.output["item"]["id"]
    cancelled = await tool.execute({"action": "cancel", "id": first_id}, context=CTX)
    assert cancelled.output["item"]["status"] == "cancelled"
    assert (await tool.execute({"action": "cancel", "id": 9999}, context=CTX)).output["updated"] is False
    remaining = await tool.query({"action": "query", **_custom(NOW, NOW + timedelta(days=2))}, now=NOW, owner=OWNER)
    assert [item["schedule_id"] for item in remaining.output["items"]] == [second_id]
    tool.close()


@pytest.mark.asyncio
async def test_schedule_notification_is_deduplicated_across_restart(tmp_path):
    path = tmp_path / "schedules.db"
    notifications: list[dict] = []

    async def callback(item):
        notifications.append(item)

    tool = ScheduleTool(path, callback=callback)
    await tool.execute(
        {
            "action": "create",
            "title": "提醒一次",
            "start_text": "2026-07-28 10:15",
            "notify_before_minutes": 15,
        }
    , context=CTX)
    assert await tool.poll_due(now=NOW) == 1
    assert await tool.poll_due(now=NOW) == 0
    tool.close()
    reopened = ScheduleTool(path, callback=callback)
    assert await reopened.poll_due(now=NOW) == 0
    assert len(notifications) == 1
    reopened.close()


@pytest.mark.asyncio
async def test_schedule_scheduler_lifecycle_is_managed(tmp_path):
    tool = ScheduleTool(tmp_path / "schedules.db")
    await tool.start_scheduler()
    assert tool._scheduler_task is not None
    await tool.stop_scheduler()
    assert tool._scheduler_task is None
    tool.close()
