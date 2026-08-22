from datetime import datetime
from pathlib import Path

import pytest

from agent_platform.adapters.mock_adapter import MockModelAdapter
from agent_platform.api.container import ApplicationContainer
from agent_platform.config import Settings
from agent_platform.core.model_gateway import ModelGateway
from agent_platform.core.parameter_normalizer import deterministic_pre_route_arguments, normalize_arguments
from agent_platform.models import AuditEventType, TaskConfirmation, TaskCreate, TaskState, is_argument_extraction_schema

from agent_platform.models import ToolContext

CTX = ToolContext(owner="default")
OWNER = "default"


def test_alias_normalization_is_scoped_and_does_not_mutate_input():
    knowledge_arguments = {"question": "\u4ea7\u54c1\u4fdd\u4fee\u671f"}
    knowledge = normalize_arguments(
        intent="knowledge_query",
        arguments=knowledge_arguments,
        request_text="\u67e5\u8be2\u4ea7\u54c1\u4fdd\u4fee\u671f",
    )
    assert knowledge.arguments == {"query": "\u4ea7\u54c1\u4fdd\u4fee\u671f"}
    assert knowledge.applied_rules == ["knowledge_query.question_to_query"]
    assert knowledge_arguments == {"question": "\u4ea7\u54c1\u4fdd\u4fee\u671f"}

    file_result = normalize_arguments(
        intent="file_open",
        arguments={"keyword": "readme.md"},
        request_text="\u6253\u5f00 readme.md",
    )
    assert file_result.arguments == {"query": "readme.md"}
    assert file_result.applied_rules == ["file_open.keyword_to_query"]

    unrelated = normalize_arguments(
        intent="reminder_create",
        arguments={"question": "\u4e0d\u5e94\u8be5\u4fee\u6539"},
        request_text="\u63d0\u9192\u6211",
    )
    assert unrelated.arguments == {"question": "\u4e0d\u5e94\u8be5\u4fee\u6539"}
    assert unrelated.applied_rules == []

    wrapped = normalize_arguments(
        intent="knowledge_query",
        arguments={"query": "知识库 安全规范"},
        request_text="知识库里有安全规范吗",
    )
    assert wrapped.arguments == {"query": "安全规范"}
    assert wrapped.applied_rules == ["knowledge_query.strip_knowledge_wrapper"]


@pytest.mark.parametrize(
    ("request_text", "expected_path"),
    [
        ("\u6574\u7406\u4f1a\u8bae\u8bb0\u5f55 C:\\demo\\m1.txt", r"C:\demo\m1.txt"),
        ("\u6574\u7406\u4f1a\u8bae\u8bb0\u5f55 /tmp/meeting.md", "/tmp/meeting.md"),
    ],
)
def test_meeting_path_is_repaired_only_from_one_literal_absolute_path(request_text, expected_path):
    result = normalize_arguments(
        intent="meeting_process",
        arguments={"source_path": "\\broken\\path.md"},
        request_text=request_text,
    )
    assert result.arguments == {"source_path": expected_path}
    assert result.applied_rules == ["meeting_process.source_path_from_request"]


def test_meeting_path_is_not_guessed_when_request_contains_multiple_paths():
    result = normalize_arguments(
        intent="meeting_process",
        arguments={"source_path": "\\broken\\path.md"},
        request_text="\u5bf9\u6bd4 C:\\demo\\first.txt \u548c /tmp/second.md",
    )
    assert result.arguments == {"source_path": "\\broken\\path.md"}
    assert result.applied_rules == []


def test_reminder_rules_only_change_unambiguous_request_text():
    cancel = normalize_arguments(
        intent="reminder_create",
        arguments={"action": "delete_all"},
        request_text="\u53d6\u6d88\u63d0\u9192 12",
    )
    assert cancel.arguments == {"action": "cancel", "id": 12}
    assert cancel.applied_rules == ["reminder_create.cancel_with_id_from_request"]

    delete_all = normalize_arguments(
        intent="reminder_create",
        arguments={"action": "query", "text": "x"},
        request_text="\u5220\u9664\u5168\u90e8\u63d0\u9192",
    )
    assert delete_all.arguments["action"] == "delete_all"
    assert delete_all.applied_rules == ["reminder_create.delete_all_from_request"]

    clear_all = normalize_arguments(
        intent="reminder_create",
        arguments={},
        request_text="\u6e05\u7a7a\u5168\u90e8\u63d0\u9192",
    )
    assert clear_all.arguments == {"action": "delete_all"}
    assert clear_all.applied_rules == ["reminder_create.delete_all_from_request"]

    descriptive_cancel = normalize_arguments(
        intent="reminder_create",
        arguments={"action": "create"},
        request_text="\u53d6\u6d88\u63d0\u9192 12 \u6708 5 \u65e5\u7684\u4f1a\u8bae",
    )
    assert descriptive_cancel.arguments == {"action": "create"}
    assert descriptive_cancel.applied_rules == []

    negated_delete = normalize_arguments(
        intent="reminder_create",
        arguments={"action": "query"},
        request_text="\u4e0d\u8981\u5220\u9664\u5168\u90e8\u63d0\u9192",
    )
    assert negated_delete.arguments == {"action": "query"}
    assert negated_delete.applied_rules == []

    overdue = normalize_arguments(
        intent="reminder_create",
        arguments={"action": "query", "scope": "past_events"},
        request_text="\u67e5\u770b\u8fc7\u53bb\u672a\u5b8c\u6210\u7684\u5f85\u529e",
    )
    assert overdue.arguments == {"action": "query", "scope": "overdue"}
    assert overdue.applied_rules == ["reminder_create.past_events_to_overdue"]

    create = normalize_arguments(
        intent="reminder_create",
        arguments={"action": "create", "text": "\u5f00\u4f1a", "scope": "in_30_minutes"},
        request_text="\u63d0\u9192\u621130\u5206\u949f\u540e\u5f00\u4f1a",
    )
    assert create.arguments == {"action": "create", "text": "\u5f00\u4f1a", "when": "\u63d0\u9192\u621130\u5206\u949f\u540e\u5f00\u4f1a"}
    assert create.applied_rules == [
        "reminder_create.drop_scope_for_create",
        "reminder_create.when_from_request",
    ]


def test_text_operation_normalization_respects_explicit_non_default_operation():
    summarized = normalize_arguments(
        intent="text_polish",
        arguments={"operation": "polish", "text": "x"},
        request_text="\u7f29\u5199\uff1a\u8fd9\u662f\u9700\u8981\u538b\u7f29\u7684\u5185\u5bb9",
    )
    assert summarized.arguments["operation"] == "summarize"
    assert summarized.applied_rules == ["text_polish.summarize_from_request"]

    draft = normalize_arguments(
        intent="text_polish",
        arguments={"operation": "draft", "text": "x"},
        request_text="\u603b\u7ed3\uff1a\u8fd9\u662f\u9700\u8981\u5904\u7406\u7684\u5185\u5bb9",
    )
    assert draft.arguments["operation"] == "draft"
    assert draft.applied_rules == []

    rewrite = normalize_arguments(
        intent="text_polish",
        arguments={"operation": "rewrite", "text": "x"},
        request_text="\u6539\u5199\uff1a\u8fd9\u6bb5\u8bdd",
    )
    assert rewrite.arguments["operation"] == "polish"
    assert rewrite.applied_rules == ["text_polish.operation_to_polish"]

    draft_from_request = normalize_arguments(
        intent="text_polish",
        arguments={"operation": "polish", "text": "x"},
        request_text="\u8349\u62df\uff1a\u4f1a\u8bae\u901a\u77e5",
    )
    assert draft_from_request.arguments["operation"] == "draft"
    assert draft_from_request.applied_rules == ["text_polish.draft_from_request"]

    tone = normalize_arguments(
        intent="text_polish",
        arguments={"operation": "polish", "text": "x", "tone": "urgent"},
        request_text="\u8bed\u6c14\u8c03\u6574\uff1a\u8bf7\u5c3d\u5feb\u63d0\u4ea4",
    )
    assert tone.arguments == {"operation": "tone_adjust", "text": "x"}
    assert tone.applied_rules == ["text_polish.tone_adjust_from_request"]

    formal = normalize_arguments(
        intent="text_polish",
        arguments={"operation": "polish", "text": "x"},
        request_text="调整为正式语气：麻烦大家记得下午一点开会",
    )
    assert formal.arguments == {"operation": "tone_adjust", "text": "x", "tone": "formal"}
    assert formal.applied_rules == ["text_polish.tone_adjust_from_request"]


def test_todo_priority_normalization_is_whitelisted_and_never_invents_an_id():
    result = normalize_arguments(
        intent="todo_manage",
        arguments={"action": "create", "title": "提交报告", "priority": "高优先级"},
        request_text="添加待办：提交报告，高优先级",
    )
    assert result.arguments == {"action": "create", "title": "提交报告", "priority": "high"}
    assert result.applied_rules == ["todo_manage.priority_to_canonical"]

    untouched = normalize_arguments(
        intent="todo_manage",
        arguments={"action": "complete", "title_query": "提交报告"},
        request_text="完成待办 提交报告",
    )
    assert "id" not in untouched.arguments
    assert untouched.arguments == {"action": "query", "title_query": "提交报告"}
    assert untouched.applied_rules == ["todo_manage.title_mutation_to_query"]


def test_schedule_normalization_only_extracts_unambiguous_id_or_range():
    cancel = normalize_arguments(
        intent="schedule_manage",
        arguments={"action": "query"},
        request_text="取消日程 8",
    )
    assert cancel.arguments == {"action": "cancel", "id": 8}
    assert cancel.applied_rules == ["schedule_manage.cancel_with_id_from_request"]

    today = normalize_arguments(
        intent="schedule_manage",
        arguments={"action": "query"},
        request_text="今天下午有什么安排",
    )
    assert today.arguments["range"] == "today"
    assert today.applied_rules == ["schedule_manage.今天_to_today"]

    title_cancel = normalize_arguments(
        intent="schedule_manage",
        arguments={"action": "cancel", "title_query": "项目例会"},
        request_text="取消日程 项目例会",
    )
    assert title_cancel.arguments == {"action": "query", "title_query": "项目例会"}
    assert title_cancel.applied_rules == ["schedule_manage.cancel_title_to_query"]

    weekly = normalize_arguments(
        intent="schedule_manage",
        arguments={"action": "create", "title": "站会", "start_text": "每周一三五上午9点"},
        request_text="创建日程 每周一三五上午9点站会",
    )
    assert weekly.arguments["recurrence"] == "weekly"
    assert weekly.arguments["weekdays"] == [0, 2, 4]
    assert weekly.applied_rules == [
        "schedule_manage.weekly_recurrence_from_request",
        "schedule_manage.weekdays_from_request",
    ]


def test_schedule_create_restores_request_time_and_moves_model_range_end():
    result = normalize_arguments(
        intent="schedule_manage",
        arguments={
            "action": "create",
            "title": "上线评审",
            "start_text": "2026-08-01 09:00",
            "range_end": "2026-08-08T10:00:00+08:00",
        },
        request_text="创建日程：2026年8月8日上午9点到10点上线评审",
    )

    # The matched time cue (not the whole request sentence) becomes the
    # bounded start_text the schedule parser consumes.
    assert result.arguments["start_text"] == "2026年8月8日上午9点到10点"
    assert result.arguments["end_text"] == "2026-08-08T10:00:00+08:00"
    assert "range_end" not in result.arguments
    assert result.applied_rules == [
        "schedule_manage.range_end_to_end_text",
        "schedule_manage.start_text_from_request",
    ]


def test_deterministic_small_model_arguments_cover_literal_id_and_query_anchors():
    assert deterministic_pre_route_arguments("todo_manage", "添加待办 整理材料，高优先级") == {
        "action": "create",
        "title": "整理材料",
        "priority": "high",
    }
    assert deterministic_pre_route_arguments("reminder_create", "待办：1小时后检查服务") == {
        "action": "create",
        "text": "检查服务",
        "when": "1小时后",
    }
    assert deterministic_pre_route_arguments("reminder_create", "清空全部提醒") == {
        "action": "delete_all",
    }
    assert deterministic_pre_route_arguments("reminder_create", "完成提醒 ID 7") == {
        "action": "complete",
        "id": 7,
    }
    assert deterministic_pre_route_arguments("reminder_create", "查看未来7天提醒") == {
        "action": "query",
        "scope": "next_7_days",
    }
    assert deterministic_pre_route_arguments("todo_manage", "更新待办 ID 3 为进行中") == {
        "action": "update",
        "id": 3,
        "status": "in_progress",
    }
    assert deterministic_pre_route_arguments("todo_manage", "完成待办 ID 2") == {
        "action": "complete",
        "id": 2,
    }
    assert deterministic_pre_route_arguments("todo_manage", "查看已完成待办") == {
        "action": "query",
        "status": "completed",
    }
    assert deterministic_pre_route_arguments("schedule_manage", "查询日程 产品评审") == {
        "action": "query",
        "title_query": "产品评审",
    }
    assert deterministic_pre_route_arguments("todo_manage", "帮我处理一下待办") is None


def test_schedule_create_restores_uppercase_chinese_date_from_request():
    result = normalize_arguments(
        intent="schedule_manage",
        arguments={
            "action": "create",
            "id": 123,
            "title": "产品评审",
            "start_text": "上午九点到上午十点",
        },
        request_text="创建日程 二〇二六年八月八日上午九点到上午十点 产品评审",
    )

    assert result.arguments["start_text"] == "二〇二六年八月八日上午九点到上午十点"
    assert result.applied_rules == ["schedule_manage.start_text_from_request"]


class _QuestionAliasAdapter(MockModelAdapter):
    async def generate(self, messages, response_schema, max_tokens=512):
        if messages[-1].content == "\u67e5\u8be2\u4fdd\u4fee\u671f" and is_argument_extraction_schema(response_schema):
            return {
                "arguments": {"question": "\u4fdd\u4fee\u671f"},
                "missing_fields": [],
            }
        return await super().generate(messages, response_schema, max_tokens)


class _DeleteAllAsCreateAdapter(MockModelAdapter):
    async def generate(self, messages, response_schema, max_tokens=512):
        if messages[-1].content == "\u5220\u9664\u5168\u90e8\u63d0\u9192" and is_argument_extraction_schema(response_schema):
            return {
                "arguments": {"action": "create", "text": "\u5220\u9664\u5168\u90e8\u63d0\u9192"},
                "missing_fields": [],
            }
        return await super().generate(messages, response_schema, max_tokens)


class _CancelWithoutIdAdapter(MockModelAdapter):
    async def generate(self, messages, response_schema, max_tokens=512):
        if messages[-1].content == "取消提醒 12" and is_argument_extraction_schema(response_schema):
            return {
                "arguments": {"action": "cancel", "text": "取消提醒 12"},
                "missing_fields": [],
            }
        return await super().generate(messages, response_schema, max_tokens)


def _settings(tmp_path: Path) -> Settings:
    allowed = tmp_path / "allowed"
    knowledge = tmp_path / "knowledge"
    allowed.mkdir()
    knowledge.mkdir()
    return Settings(
        model_provider="mock",
        database_path=tmp_path / "agent.db",
        audit_dir=tmp_path / "audit",
        authorized_file_roots=[allowed],
        knowledge_roots=[knowledge],
        meeting_output_dir=tmp_path / "meeting",
        audit_flush_size=1,
    )


@pytest.mark.asyncio
async def test_agent_uses_deterministic_knowledge_arguments_before_schema_validation(tmp_path):
    container = ApplicationContainer.build(_settings(tmp_path))
    gateway = ModelGateway(_QuestionAliasAdapter())
    container.gateway = gateway
    container.agent._gateway = gateway
    try:
        task = await container.agent.submit(TaskCreate(text="\u67e5\u8be2\u4fdd\u4fee\u671f"))
        assert task.state == TaskState.COMPLETED
        assert task.context["arguments"] == {"query": "\u4fdd\u4fee\u671f"}
        assert task.context["normalization_rules"] == []
    finally:
        await container.close()


@pytest.mark.asyncio
async def test_agent_normalizes_delete_all_before_policy_and_audits_it(tmp_path):
    container = ApplicationContainer.build(_settings(tmp_path))
    gateway = ModelGateway(_DeleteAllAsCreateAdapter())
    container.gateway = gateway
    container.agent._gateway = gateway
    try:
        task = await container.agent.submit(TaskCreate(text="\u5220\u9664\u5168\u90e8\u63d0\u9192"))
        assert task.state == TaskState.AWAITING_CONFIRMATION
        assert task.risk_level.value == "R3"
        assert task.context["arguments"]["action"] == "delete_all"
        assert task.context["normalization_rules"] == ["reminder_create.delete_all_from_request"]

        events = await container.audit.by_task(task.id)
        normalized = [event for event in events if event.decision == "parameters_normalized"]
        assert len(normalized) == 1
        assert "reminder_create.delete_all_from_request" in normalized[0].output_summary
        assert all(event.event_type != AuditEventType.TOOL_CALLED for event in events)
    finally:
        await container.close()


@pytest.mark.asyncio
async def test_agent_accepts_cancel_candidate_then_normalizes_id_before_contract_check(tmp_path):
    container = ApplicationContainer.build(_settings(tmp_path))
    gateway = ModelGateway(_CancelWithoutIdAdapter())
    container.gateway = gateway
    container.agent._gateway = gateway
    try:
        task = await container.agent.submit(TaskCreate(text="取消提醒 12"))
        assert task.state == TaskState.COMPLETED
        assert task.context["arguments"]["action"] == "cancel"
        assert task.context["arguments"]["id"] == 12
    finally:
        await container.close()


@pytest.mark.asyncio
async def test_todo_title_request_queries_candidates_and_delete_waits_for_confirmation(tmp_path):
    container = ApplicationContainer.build(_settings(tmp_path))
    try:
        first = await container.todos.execute({"action": "create", "title": "提交报告"}, context=CTX)
        second = await container.todos.execute({"action": "create", "title": "提交报告"}, context=CTX)
        first_id = first.output["item"]["id"]
        second_id = second.output["item"]["id"]

        candidate_task = await container.agent.submit(TaskCreate(text="完成待办 提交报告"))
        assert candidate_task.state == TaskState.COMPLETED
        candidates = candidate_task.result["output"]["items"]
        assert {item["id"] for item in candidates} == {first_id, second_id}
        assert all(item["status"] == "pending" for item in candidates)

        delete_task = await container.agent.submit(TaskCreate(text=f"删除待办 {first_id}"))
        assert delete_task.state == TaskState.AWAITING_CONFIRMATION
        events = await container.audit.by_task(delete_task.id)
        assert all(event.event_type != AuditEventType.TOOL_CALLED for event in events)
        completed = await container.agent.confirm(delete_task.id, TaskConfirmation(arguments={}, approved=True))
        assert completed.state == TaskState.COMPLETED
        remaining = await container.todos.execute({"action": "query", "title_query": "提交报告"}, context=CTX)
        assert [item["id"] for item in remaining.output["items"]] == [second_id]
    finally:
        await container.close()


@pytest.mark.asyncio
async def test_schedule_title_request_queries_candidates_and_cancel_preview_is_pre_execution(tmp_path):
    container = ApplicationContainer.build(_settings(tmp_path))
    try:
        first = await container.schedules.execute(
            {"action": "create", "title": "项目例会", "start_text": "2026-07-29 14:00"}
        , context=CTX)
        second = await container.schedules.execute(
            {"action": "create", "title": "项目例会", "start_text": "2026-07-30 14:00"}
        , context=CTX)
        first_id = first.output["item"]["id"]
        second_id = second.output["item"]["id"]

        candidate_task = await container.agent.submit(TaskCreate(text="取消日程 项目例会"))
        assert candidate_task.state == TaskState.COMPLETED
        candidates = candidate_task.result["output"]["items"]
        assert {item["schedule_id"] for item in candidates} == {first_id, second_id}

        cancel_task = await container.agent.submit(TaskCreate(text=f"取消日程 {first_id}"))
        assert cancel_task.state == TaskState.AWAITING_CONFIRMATION
        confirmation = cancel_task.result["confirmation"]
        assert "项目例会" in confirmation["content"]
        assert first.output["item"]["start_at"] in confirmation["content"]
        events = await container.audit.by_task(cancel_task.id)
        assert all(event.event_type != AuditEventType.TOOL_CALLED for event in events)
        completed = await container.agent.confirm(cancel_task.id, TaskConfirmation(arguments={}, approved=True))
        assert completed.state == TaskState.COMPLETED
        remaining = await container.schedules.query(
            {
                "action": "query",
                "range": "custom",
                "range_start": "2026-07-28T00:00:00+08:00",
                "range_end": "2026-08-01T00:00:00+08:00",
            },
            now=datetime.fromisoformat("2026-07-28T10:00:00+08:00"),
         owner=OWNER)
        assert [item["schedule_id"] for item in remaining.output["items"]] == [second_id]
    finally:
        await container.close()
