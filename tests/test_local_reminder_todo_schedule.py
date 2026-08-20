from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from agent_platform.core.intent_router import pre_route_intent
from agent_platform.core.parameter_normalizer import normalize_arguments
from agent_platform.core.tool_executor import ToolExecutor
from agent_platform.core.tool_registry import ToolRegistry
from agent_platform.models import INTENT_RESPONSE_SCHEMA, MessageRole, ModelMessage, TaskCreate, ToolCall
from agent_platform.adapters.mock_adapter import MockModelAdapter
from agent_platform.api.container import ApplicationContainer
from agent_platform.config import Settings
from agent_platform.tools.reminder_tool import ChineseTimeParser, ReminderTool, clean_reminder_text
from agent_platform.tools.schedule_tool import ScheduleTool
from agent_platform.tools.todo_tool import TodoTool

from agent_platform.models import ToolContext

CTX = ToolContext(owner="default")
OWNER = "default"


TZ = ZoneInfo("Asia/Shanghai")


@pytest.mark.asyncio
async def test_reminder_query_cache_does_not_hide_new_or_deleted_rows(tmp_path: Path) -> None:
    reminders = ReminderTool(tmp_path / "reminders.db")
    registry = ToolRegistry()
    registry.register(reminders)
    registry.freeze()
    executor = ToolExecutor(registry)

    async def call(arguments: dict[str, object]):
        return await executor.execute(ToolCall(task_id=uuid4(), tool_name="reminder_create", arguments=arguments), context=CTX)

    assert (await call({"action": "query"})).output["items"] == []
    first = await call({"action": "create", "text": "提醒我1分钟后甲"})
    second = await call({"action": "create", "text": "提醒我2分钟后乙"})
    assert first.output["item"]["text"] == "甲"
    assert second.output["item"]["text"] == "乙"
    queried = await call({"action": "query"})
    assert [item["text"] for item in queried.output["items"]] == ["甲", "乙"]

    deleted = await call({"action": "delete_all"})
    assert deleted.output["deleted_count"] == 2
    assert [item["text"] for item in deleted.output["deleted_items"]] == ["甲", "乙"]
    assert (await call({"action": "query"})).output["items"] == []
    reminders.close()


def test_reminder_text_cleanup_and_chinese_number_parser() -> None:
    assert clean_reminder_text("提醒我：开会") == "开会"
    assert clean_reminder_text("提醒我1分钟后有闪") == "有闪"
    assert clean_reminder_text("1分钟后提醒我有闪") == "有闪"

    parser = ChineseTimeParser()
    now = datetime(2026, 8, 6, 8, 0, tzinfo=TZ)
    due, repeat = parser.parse("十五分钟后", now=now)
    assert due == now + timedelta(minutes=15)
    assert repeat is None
    due, repeat = parser.parse("贰零贰陆年捌月捌日上午玖点", now=now)
    assert due == datetime(2026, 8, 8, 9, 0, tzinfo=TZ)
    assert repeat is None
    due, repeat = parser.parse("每周一上午九点", now=now)
    assert due.weekday() == 0
    assert due.hour == 9
    assert due.minute == 0
    assert repeat == "weekly:0:09:00"


def test_todo_status_and_update_request_normalization() -> None:
    status = normalize_arguments(
        intent="todo_manage",
        arguments={"action": "query", "title_query": "查看进行中待办"},
        request_text="查看进行中待办",
    )
    assert status.arguments == {"action": "query", "status": "in_progress"}

    update = normalize_arguments(
        intent="todo_manage",
        arguments={"action": "query", "title_query": "更新待办 7 为高优先级"},
        request_text="更新待办 7 为高优先级",
    )
    assert update.arguments == {"action": "update", "id": 7, "priority": "high"}


@pytest.mark.asyncio
async def test_reminder_complete_request_is_understood_by_offline_adapter() -> None:
    adapter = MockModelAdapter()
    generated = await adapter.generate(
        [ModelMessage(role=MessageRole.USER, content="完成提醒 3")],
        INTENT_RESPONSE_SCHEMA,
    )
    assert generated["arguments"]["action"] == "complete"
    normalized = normalize_arguments(
        intent="reminder_create",
        arguments=generated["arguments"],
        request_text="完成提醒 3",
    )
    assert normalized.arguments == {"action": "complete", "text": "完成提醒 3", "id": 3}
    assert "reminder_create.complete_with_id_from_request" in normalized.applied_rules


def _agent_settings(tmp_path: Path) -> Settings:
    return Settings(
        model_provider="mock",
        database_path=tmp_path / "agent.db",
        audit_dir=tmp_path / "audit",
        authorized_file_roots=[tmp_path / "allowed"],
        knowledge_roots=[tmp_path / "knowledge"],
        meeting_output_dir=tmp_path / "meeting",
        audit_flush_size=1,
    )


@pytest.mark.asyncio
async def test_agent_reminder_completion_and_confirmation_previews_are_readable(tmp_path: Path) -> None:
    settings = _agent_settings(tmp_path)
    container = ApplicationContainer.build(settings)
    await container.initialize()
    try:
        created = await container.agent.submit(TaskCreate(text="1分钟后提醒我有闪"))
        assert created.state.value == "completed"
        reminder_item = created.result["output"]["item"]
        assert reminder_item["text"] == "有闪"

        completed = await container.agent.submit(TaskCreate(text=f"完成提醒 {reminder_item['id']}"))
        assert completed.state.value == "completed"
        assert completed.result["output"]["item"]["status"] == "completed"

        todo = await container.todos.execute({"action": "create", "title": "删除前可读"}, context=CTX)
        todo_id = int(todo.output["item"]["id"])
        delete_task = await container.agent.submit(TaskCreate(text=f"删除待办 {todo_id}"))
        assert delete_task.state.value == "awaiting_confirmation"
        content = delete_task.result["confirmation"]["content"]
        assert "删除前可读" in content
        assert "状态：pending" in content
    finally:
        await container.close()


@pytest.mark.asyncio
async def test_todo_status_queries_and_update_return_business_content(tmp_path: Path) -> None:
    tool = TodoTool(tmp_path / "todos.db")
    first = await tool.execute({"action": "create", "title": "提交报告"}, context=CTX)
    second = await tool.execute({"action": "create", "title": "部署服务"}, context=CTX)
    first_id = int(first.output["item"]["id"])
    second_id = int(second.output["item"]["id"])
    await tool.execute({"action": "update", "id": first_id, "status": "in_progress"}, context=CTX)
    await tool.execute({"action": "complete", "id": second_id}, context=CTX)

    active = await tool.execute({"action": "query", "status": "进行中"}, context=CTX)
    completed = await tool.execute({"action": "query", "status": "已完成"}, context=CTX)
    pending = await tool.execute({"action": "query", "status": "待处理"}, context=CTX)
    assert [item["title"] for item in active.output["items"]] == ["提交报告"]
    assert [item["title"] for item in completed.output["items"]] == ["部署服务"]
    assert pending.output["items"] == []

    updated = await tool.execute({"action": "update", "id": first_id, "priority": "high"}, context=CTX)
    assert updated.output["item"]["title"] == "提交报告"
    assert "提交报告" in updated.output_summary
    completed_summary = await tool.execute({"action": "complete", "id": first_id}, context=CTX)
    assert "提交报告" in completed_summary.output_summary
    deleted = await tool.execute({"action": "delete", "id": second_id}, context=CTX)
    assert "部署服务" in deleted.output_summary
    tool.close()


def test_schedule_query_route_covers_week_arrangement() -> None:
    decision = pre_route_intent("本周有什么安排")
    assert decision is not None
    assert decision.intent == "schedule_manage"


@pytest.mark.asyncio
async def test_offline_schedule_title_query_is_not_limited_to_default_week() -> None:
    adapter = MockModelAdapter()
    generated = await adapter.generate(
        [ModelMessage(role=MessageRole.USER, content="查询日程 项目例会")],
        INTENT_RESPONSE_SCHEMA,
    )
    assert generated["arguments"] == {"action": "query", "title_query": "项目例会"}

    ranged = await adapter.generate(
        [ModelMessage(role=MessageRole.USER, content="本周有什么安排，标题包含项目例会")],
        INTENT_RESPONSE_SCHEMA,
    )
    assert ranged["arguments"] == {"action": "query", "range": "this_week", "title_query": "项目例会"}

    todo = await adapter.generate(
        [ModelMessage(role=MessageRole.USER, content="查看待处理待办，标题包含部署服务")],
        INTENT_RESPONSE_SCHEMA,
    )
    assert todo["arguments"] == {"action": "query", "status": "pending", "title_query": "部署服务"}


@pytest.mark.asyncio
async def test_offline_adapter_keeps_todo_and_schedule_titles_free_of_form_metadata() -> None:
    adapter = MockModelAdapter()
    todo = await adapter.generate(
        [ModelMessage(role=MessageRole.USER, content="添加待办 部署服务，中优先级")],
        INTENT_RESPONSE_SCHEMA,
    )
    schedule = await adapter.generate(
        [
            ModelMessage(
                role=MessageRole.USER,
                content="创建日程 贰零贰陆年捌月捌日上午玖点项目例会，结束上午拾点，提前15分钟提醒",
            )
        ],
        INTENT_RESPONSE_SCHEMA,
    )
    assert todo["arguments"]["title"] == "部署服务"
    assert todo["arguments"]["priority"] == "medium"
    assert schedule["arguments"]["title"] == "项目例会"
    assert schedule["arguments"]["end_text"] == "上午拾点"
    assert schedule["arguments"]["notify_before_minutes"] == 15


@pytest.mark.asyncio
async def test_schedule_uppercase_date_and_chinese_end_time_are_queryable(tmp_path: Path) -> None:
    tool = ScheduleTool(tmp_path / "schedules.db")
    created = await tool.execute(
        {
            "action": "create",
            "title": "项目例会",
            "start_text": "贰零贰陆年捌月捌日上午玖点到十点",
        }
    , context=CTX)
    item = created.output["item"]
    assert item["start_at"] == "2026-08-08T09:00:00+08:00"
    assert item["end_at"] == "2026-08-08T10:00:00+08:00"
    queried = await tool.query(
        {
            "action": "query",
            "range": "custom",
            "range_start": "2026-08-06T00:00:00+08:00",
            "range_end": "2026-08-10T00:00:00+08:00",
        },
        now=datetime(2026, 8, 6, 8, 0, tzinfo=TZ),
     owner=OWNER)
    assert [entry["schedule_id"] for entry in queried.output["items"]] == [item["id"]]
    tool.close()


def test_schedule_parser_accepts_financial_numerals_in_time_of_day() -> None:
    parser = ChineseTimeParser()
    hour, minute = parser.parse_time_of_day("下午拾点半")
    assert (hour, minute) == (22, 30)


__all__ = []
