from pathlib import Path

import pytest

from agent_platform.adapters.mock_adapter import MockModelAdapter
from agent_platform.adapters.platform import DisabledFileOpener
from agent_platform.config import Settings
from agent_platform.core.data_classification import DataClassificationService
from agent_platform.core.parameter_normalizer import normalize_arguments
from agent_platform.models import INTENT_RESPONSE_SCHEMA, MessageRole, ModelMessage
from agent_platform.tools.file_search_tool import FileSearchTool
from agent_platform.tools.knowledge_base_tool import KnowledgeBaseTool
from agent_platform.tools.meeting_notes_tool import MeetingNotesTool


def test_default_resource_roots_follow_checkout_when_started_elsewhere(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    settings = Settings(_env_file=None)
    checkout = Path(__file__).parents[1]

    assert settings.authorized_file_roots[-1] == checkout / "demo_documents"
    assert settings.knowledge_roots[-1] == checkout / "demo_documents"
    assert settings.database_path == checkout / "data" / "agent_platform.db"


@pytest.mark.asyncio
async def test_demo_knowledge_file_and_meeting_tools_work_from_foreign_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = Settings(
        _env_file=None,
        database_path=tmp_path / "agent.db",
        audit_dir=tmp_path / "audit",
        meeting_output_dir=tmp_path / "meeting",
    )
    classifier = DataClassificationService()

    file_tool = FileSearchTool(settings.authorized_file_roots, DisabledFileOpener())
    file_receipt = await file_tool.execute({"query": "\u9879\u76ee\u5468\u62a5"})
    assert file_receipt.output["requires_confirmation"] is True
    assert {item["name"] for item in file_receipt.output["candidates"]} >= {
        "\u9879\u76ee\u5468\u62a5_20260714.txt",
        "\u9879\u76ee\u5468\u62a5_20260721.txt",
    }

    knowledge = KnowledgeBaseTool(
        settings.knowledge_roots,
        tmp_path / "knowledge.db",
        classifier,
    )
    try:
        receipt = await knowledge.execute({"query": "\u4ea7\u54c1\u4fdd\u4fee\u671f\u662f\u591a\u4e45"})
        assert receipt.output["sources"]
        assert "\u4e24\u5e74" in receipt.output["answer"]
    finally:
        knowledge.close()

    source = settings.authorized_file_roots[-1] / "\u9879\u76ee\u5468\u62a5_20260721.txt"
    meeting = MeetingNotesTool(settings.authorized_file_roots, settings.meeting_output_dir, classifier)
    meeting_receipt = await meeting.execute({"source_path": str(source)})
    output_path = Path(meeting_receipt.output["output_path"])
    assert meeting_receipt.success is True
    assert output_path.is_file()
    assert "## \u4e3b\u8981\u8ba8\u8bba\u70b9" in output_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_workbench_prefixes_are_stripped_before_search():
    adapter = MockModelAdapter()
    text = "\u67e5\u627e\u5e76\u6253\u5f00\u6587\u4ef6\uff1a\u9879\u76ee\u5468\u62a5"
    result = await adapter.generate(
        [ModelMessage(role=MessageRole.USER, content=text)],
        INTENT_RESPONSE_SCHEMA,
    )
    assert result["arguments"]["query"] == "\u9879\u76ee\u5468\u62a5"
    normalized = normalize_arguments(
        intent="file_open",
        arguments={"query": "\u5e76\u6253\u5f00\u6587\u4ef6\uff1a\u9879\u76ee\u5468\u62a5"},
        request_text=text,
    )
    assert normalized.arguments["query"] == "\u9879\u76ee\u5468\u62a5"
    assert "file_open.strip_command_wrapper" in normalized.applied_rules

    knowledge_text = "\u67e5\u8be2\u77e5\u8bc6\u5e93\uff1a\u4ea7\u54c1\u4fdd\u4fee\u671f\u662f\u591a\u4e45\uff1f"
    knowledge = normalize_arguments(
        intent="knowledge_query",
        arguments={"query": "\u77e5\u8bc6\u5e93\uff1a\u4ea7\u54c1\u4fdd\u4fee\u671f\u662f\u591a\u4e45\uff1f"},
        request_text=knowledge_text,
    )
    assert knowledge.arguments["query"] == "\u4ea7\u54c1\u4fdd\u4fee\u671f\u662f\u591a\u4e45"
    assert "knowledge_query.strip_knowledge_wrapper" in knowledge.applied_rules
