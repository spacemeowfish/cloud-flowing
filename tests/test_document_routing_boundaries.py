from pathlib import Path

import pytest

from agent_platform.config import Settings
from agent_platform.core.data_classification import DataClassificationService
from agent_platform.core.intent_router import pre_route_intent
from agent_platform.models import (
    CLASSIFICATION_INTENT_NAMES,
    INTENT_CLASSIFICATION_SCHEMA,
    TERMINAL_INTENT_NAMES,
)
from agent_platform.tools.knowledge_base_tool import KnowledgeBaseTool
from agent_platform.tools.schedule_tool import ScheduleTool

from agent_platform.models import ToolContext

CTX = ToolContext(owner="default")
OWNER = "default"


@pytest.mark.parametrize(
    ("text", "intent"),
    [
        ("查询会议室使用规则", "knowledge_query"),
        ("查看项目周报", "file_open"),
        ("项目周报中完成了什么", "knowledge_query"),
        ("总结项目周报", "knowledge_query"),
        ("提醒功能怎么用", "knowledge_query"),
        ("提醒我下午三点开会", "reminder_create"),
        ("待办清单文件在哪", "file_open"),
        ("日程管理制度是什么", "knowledge_query"),
    ],
)
def test_boundary_fast_routes_only_use_specific_anchors(text: str, intent: str):
    decision = pre_route_intent(text)
    assert decision is not None
    assert decision.intent == intent


def test_ambiguous_external_schedule_is_left_for_model_classification():
    assert pre_route_intent("本周有什么会议") is None


def test_meeting_room_booking_prefix_routes_to_local_schedule():
    decision = pre_route_intent("预约 A301 会议室")
    assert decision is not None
    assert decision.intent == "schedule_manage"


def test_classification_schema_has_terminal_results_without_registering_tools():
    assert set(TERMINAL_INTENT_NAMES).issubset(set(INTENT_CLASSIFICATION_SCHEMA["properties"]["intent"]["enum"]))
    assert set(CLASSIFICATION_INTENT_NAMES).issuperset({"clarify", "unsupported"})


def test_document_roots_default_and_legacy_environment_fallback(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("AGENT_DOCUMENT_ROOTS", raising=False)
    monkeypatch.delenv("AGENT_AUTHORIZED_FILE_ROOTS", raising=False)
    monkeypatch.delenv("AGENT_KNOWLEDGE_ROOTS", raising=False)
    defaults = Settings(_env_file=None)
    assert [path.name for path in defaults.document_roots] == ["documents", "demo_documents"]

    files = tmp_path / "files"
    knowledge = tmp_path / "knowledge"
    monkeypatch.setenv("AGENT_AUTHORIZED_FILE_ROOTS", str(files))
    monkeypatch.setenv("AGENT_KNOWLEDGE_ROOTS", str(knowledge))
    legacy = Settings(_env_file=None)
    assert legacy.document_roots == [files, knowledge]


@pytest.mark.asyncio
async def test_project_weekly_report_uses_filename_date_and_returns_clarification(tmp_path: Path):
    root = tmp_path / "documents"
    root.mkdir()
    (root / "项目周报_20260714.txt").write_text("完成模型网关和工具注册。", encoding="utf-8")
    (root / "项目周报_20260721.txt").write_text("完成 Agent Core 状态机和知识检索回归。", encoding="utf-8")
    (root / "员工请假制度.md").write_text("员工每年享有年假。", encoding="utf-8")
    tool = KnowledgeBaseTool([root], tmp_path / "knowledge.db", DataClassificationService())

    ambiguous = await tool.execute({"query": "项目周报中完成了什么"}, context=CTX)
    assert ambiguous.output["type"] == "clarification"
    assert {item["date"] for item in ambiguous.output["candidates"]} == {"2026-07-14", "2026-07-21"}

    dated = await tool.execute({"query": "2026 年 7 月 21 日项目周报中完成了什么"}, context=CTX)
    assert "2026-07-21" in dated.output["answer"]
    assert dated.output["sources"][0]["file"] == "项目周报_20260721.txt"
    assert dated.output["sources"][0]["date"] == "2026-07-21"
    tool.close()


@pytest.mark.asyncio
async def test_local_schedule_has_room_disclaimer(tmp_path: Path):
    tool = ScheduleTool(tmp_path / "schedule.db")
    receipt = await tool.execute(
        {
            "action": "create",
            "title": "会议",
            "location": "A301",
            "start_text": "明天下午三点",
        }
    , context=CTX)
    assert receipt.output["item"]["location"] == "A301"
    assert "不代表会议室已经锁定" in receipt.output["notice"]
    tool.close()
