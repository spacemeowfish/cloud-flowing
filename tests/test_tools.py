import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from agent_platform.core.errors import SchemaValidationError
from agent_platform.core.schema_validator import SchemaValidator
from docx import Document

from agent_platform.adapters.mock_adapter import MockModelAdapter
from agent_platform.adapters.platform import DisabledFileOpener
from agent_platform.core.data_classification import DataClassificationService
from agent_platform.core.errors import PermissionDeniedError
from agent_platform.core.model_gateway import ModelGateway
from agent_platform.tools.file_search_tool import FileSearchTool
from agent_platform.tools.knowledge_base_tool import KnowledgeBaseTool
from agent_platform.tools.knowledge_importer import KnowledgeDocumentImporter
from agent_platform.tools.meeting_notes_tool import MeetingNotesTool
from agent_platform.tools.reminder_tool import ChineseTimeParser, ReminderTool
from agent_platform.tools.text_processing_tool import TextProcessingTool
from agent_platform.tools.todo_tool import TodoTool


def test_file_index_search_candidates_and_authorization(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    for index in range(10):
        (root / f"report-{index}.txt").write_text("content", encoding="utf-8")
    tool = FileSearchTool([root], DisabledFileOpener())
    assert tool.build_index() == 10
    candidates = tool.search("report")
    assert len(candidates) == 10


@pytest.mark.asyncio
async def test_file_multiple_candidates_and_open_disabled(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    (root / "plan-a.txt").write_text("a", encoding="utf-8")
    (root / "plan-b.txt").write_text("b", encoding="utf-8")
    tool = FileSearchTool([root], DisabledFileOpener())
    receipt = await tool.execute({"query": "plan"})
    assert receipt.output["requires_confirmation"] is True
    selected = receipt.output["candidates"][0]["path"]
    opened = await tool.execute({"query": "plan", "selected_path": selected})
    assert opened.output["process_status"] == "disabled_by_configuration"
    with pytest.raises(PermissionDeniedError):
        await tool.execute({"query": "x", "selected_path": str(tmp_path / "outside.txt")})


@pytest.mark.asyncio
async def test_knowledge_import_txt_md_docx_update_and_no_answer(tmp_path):
    root = tmp_path / "knowledge"
    root.mkdir()
    (root / "warranty.txt").write_text("X 产品的保修期是三年。", encoding="utf-8")
    (root / "manual.md").write_text(
        "---\nscope: 设备维护\n---\n\n# 手册\n\n设备重启需要长按电源键。",
        encoding="utf-8",
    )
    doc = Document()
    doc.add_paragraph("售后服务时间为工作日九点到十八点。")
    doc.save(root / "service.docx")
    tool = KnowledgeBaseTool([root], tmp_path / "knowledge.db", DataClassificationService())
    assert tool.sync_documents() == 3
    receipt = await tool.execute({"query": "X 产品保修期"})
    assert "三年" in receipt.output["answer"]
    assert receipt.output["sources"]
    source = receipt.output["sources"][0]
    assert source["file"] == "warranty.txt"
    assert source["section"] == "分块 1"
    assert len(source["snippet"]) <= 100
    assert source["scope"] == "未声明"
    assert "document" not in source
    missing = await tool.execute({"query": "火星基地价格"})
    assert missing.output["answer"] == "未找到相关信息"
    assert missing.output["sources"] == []
    (root / "warranty.txt").write_text("X 产品的保修期是五年。", encoding="utf-8")
    updated_mtime = (root / "warranty.txt").stat().st_mtime + 5
    os.utime(root / "warranty.txt", (updated_mtime, updated_mtime))
    assert tool.sync_documents() == 1
    updated = await tool.execute({"query": "X 产品保修期"})
    assert "五年" in updated.output["answer"]
    assert updated.output["sources"][0]["updated_at"] != source["updated_at"]
    manual = await tool.execute({"query": "设备重启"})
    assert manual.output["sources"][0]["scope"] == "设备维护"
    tool.close()


@pytest.mark.asyncio
async def test_bulk_import_utf8_bom_gb18030_idempotency_and_queries(tmp_path):
    root = tmp_path / "knowledge"
    root.mkdir()
    (root / "产品保修政策.txt").write_bytes("产品整机保修期为两年。".encode("utf-8-sig"))
    (root / "员工请假制度.md").write_text(
        "# 请假制度\n正式员工每年享有十天年假。新员工应遵守代码规范。", encoding="utf-8"
    )
    (root / "旧版差旅标准.txt").write_bytes("出差住宿标准为每晚五百元。".encode("gb18030"))
    tool = KnowledgeBaseTool([root], tmp_path / "knowledge.db", DataClassificationService())
    importer = KnowledgeDocumentImporter(tool)
    first = importer.import_directory(root)
    assert first.imported == 3
    assert not first.failures
    second = importer.import_directory(root)
    assert second.imported == 0
    assert second.skipped == 3
    forced = importer.import_directory(root, force=True)
    assert forced.imported == 3
    warranty = await tool.execute({"query": "产品保修期多久"})
    leave = await tool.execute({"query": "年假有几天"})
    travel = await tool.execute({"query": "出差住宿标准"})
    missing = await tool.execute({"query": "火星基地股票代码"})
    assert "两年" in warranty.output["answer"]
    assert "十天" in leave.output["answer"]
    assert "五百元" in travel.output["answer"]
    assert missing.output["answer"] == "未找到相关信息"
    tool.close()


TIME_CASES = [
    ("30分钟后", timedelta(minutes=30)),
    ("2小时后", timedelta(hours=2)),
    ("1天后", timedelta(days=1)),
    ("明天上午9点", timedelta(days=1)),
    ("明天下午3点", timedelta(days=1)),
    ("明天晚上8点", timedelta(days=1)),
    ("后天上午10点", timedelta(days=2)),
    ("后天下午2点", timedelta(days=2)),
    ("今天晚上11点", timedelta(0)),
    ("明天9:30", timedelta(days=1)),
    ("后天14:15", timedelta(days=2)),
    ("每周一上午9点", None),
    ("每周二下午2点", None),
    ("每周三10:30", None),
    ("每周四下午4点", None),
    ("每周五上午8点", None),
    ("每周六晚上7点", None),
    ("每周日上午11点", None),
    ("2026-08-01 15:30", None),
    ("2026年8月2日9点", None),
]


@pytest.mark.parametrize("text,delta", TIME_CASES)
def test_chinese_time_parser_twenty_expressions(text, delta):
    timezone = ZoneInfo("Asia/Shanghai")
    now = datetime(2026, 7, 28, 10, 0, tzinfo=timezone)
    due, repeat = ChineseTimeParser().parse(text, now=now)
    assert due > now
    if text.startswith("每周"):
        assert repeat and repeat.startswith("weekly")


@pytest.mark.asyncio
async def test_reminder_create_query_cancel_and_notify(tmp_path):
    notified = []

    async def callback(item):
        notified.append(item)

    tool = ReminderTool(tmp_path / "reminders.db", callback=callback)
    receipt = await tool.execute({"action": "create", "text": "30分钟后检查服务"})
    reminder_id = receipt.output["id"]
    assert tool.query("next_7_days")
    await tool.execute({"action": "cancel", "id": reminder_id})
    assert not tool.query("next_7_days")
    past = datetime.now(ZoneInfo("Asia/Shanghai")) - timedelta(minutes=1)
    tool._connection.execute(
        "INSERT INTO reminders(text,due_at,status,created_at) VALUES (?,?,?,?)",
        ("due", past.isoformat(), "active", datetime.now(UTC).isoformat()),
    )
    tool._connection.commit()
    assert await tool.poll_due() == 1
    assert notified
    tool.close()


@pytest.mark.asyncio
async def test_todo_create_query_update_complete_and_persistence(tmp_path, monkeypatch):
    tool = TodoTool(tmp_path / "todos.db")
    fixed_due = datetime(2026, 8, 1, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    monkeypatch.setattr(tool._time_parser, "parse", lambda text: (fixed_due, None))

    created = await tool.execute(
        {
            "action": "create",
            "title": "提交报告",
            "priority": "high",
            "tags": ["工作", "工作", "本周"],
            "due_text": "明天上午九点半",
        }
    )
    todo_id = created.output["item"]["id"]
    assert created.output["item"]["due_at"] == fixed_due.isoformat()
    assert created.output["item"]["tags"] == ["工作", "本周"]

    without_due = await tool.execute({"action": "create", "title": "整理桌面"})
    assert without_due.output["item"]["due_at"] is None
    assert [item["id"] for item in (await tool.execute({"action": "query", "tag": "工作"})).output["items"]] == [todo_id]
    assert (await tool.execute({"action": "query", "priority": "high"})).output["items"][0]["id"] == todo_id

    updated = await tool.execute({"action": "update", "id": todo_id, "status": "in_progress"})
    assert updated.output["item"]["status"] == "in_progress"
    completed = await tool.execute({"action": "complete", "id": todo_id})
    assert completed.output["item"]["status"] == "completed"
    assert (await tool.execute({"action": "query"})).output["items"] == [without_due.output["item"]]
    assert (await tool.execute({"action": "update", "id": 99999, "title": "不存在"})).output["updated"] is False

    assert tool._connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    with pytest.raises(sqlite3.IntegrityError):
        tool._connection.execute("UPDATE todos SET priority = 'invalid' WHERE id = ?", (todo_id,))
    tool.close()

    reopened = TodoTool(tmp_path / "todos.db")
    persisted = await reopened.execute({"action": "query", "status": "completed"})
    assert persisted.output["items"][0]["id"] == todo_id
    reopened.close()


@pytest.mark.asyncio
async def test_todo_contract_requires_id_and_unknown_delete_has_no_side_effect(tmp_path):
    tool = TodoTool(tmp_path / "todos.db")
    with pytest.raises(SchemaValidationError):
        SchemaValidator.validate({"action": "update", "title": "x"}, tool.metadata.parameters_schema)
    with pytest.raises(SchemaValidationError):
        SchemaValidator.validate({"action": "complete"}, tool.metadata.parameters_schema)
    with pytest.raises(SchemaValidationError):
        SchemaValidator.validate({"action": "delete"}, tool.metadata.parameters_schema)
    absent = await tool.execute({"action": "delete", "id": 12345})
    assert absent.output == {"updated": False, "id": 12345}
    tool.close()


@pytest.mark.asyncio
async def test_todo_unparseable_due_time_requests_clarification_without_writing(tmp_path):
    tool = TodoTool(tmp_path / "todos.db")
    result = await tool.execute({"action": "create", "title": "交报告", "due_text": "下周"})
    assert result.output["requires_confirmation"] is True
    assert result.output["fields"] == ["due_text"]
    assert tool._connection.execute("SELECT count(*) FROM todos").fetchone()[0] == 0
    tool.close()


@pytest.mark.parametrize("action", ["cancel", "complete"])
def test_reminder_contract_requires_id_for_status_changes(tmp_path, action):
    tool = ReminderTool(tmp_path / "reminders.db")
    with pytest.raises(SchemaValidationError):
        SchemaValidator.validate({"action": action}, tool.metadata.parameters_schema)
    tool.close()


@pytest.mark.asyncio
async def test_text_draft_preserves_facts():
    tool = TextProcessingTool(ModelGateway(MockModelAdapter()))
    receipt = await tool.execute(
        {"operation": "polish", "text": "项目预算300万元，日期2026年8月1日，电话13800138000。"}
    )
    text = receipt.output["text"]
    assert text.startswith("【草稿】")
    assert "300万元" in text
    assert "2026年8月1日" in text
    assert "13800138000" in text


class _TextPayloadAdapter:
    async def generate(self, messages, response_schema, max_tokens=512):
        del response_schema, max_tokens
        return {"text": messages[-1].content.rsplit("\n", 1)[-1]}

    async def close(self):
        return None


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["polish", "summarize", "tone_adjust", "draft"])
@pytest.mark.parametrize(
    "original",
    [
        "预算300万元，计划2026年8月1日上线。",
        "联系电话13800138000，请在2小时后确认。",
        "项目ABC_123已完成3项验收。",
    ],
)
async def test_each_text_operation_executes_and_preserves_protected_facts(operation, original):
    tool = TextProcessingTool(ModelGateway(_TextPayloadAdapter()))
    arguments = {"operation": operation, "text": original}
    if operation == "tone_adjust":
        arguments["tone"] = "formal"
    if operation == "summarize":
        arguments["target_length"] = 20

    receipt = await tool.execute(arguments)

    assert receipt.success is True
    assert receipt.output["status"] == "draft"
    assert receipt.output["text"].startswith("【草稿】")
    assert all(fact in receipt.output["text"] for fact in receipt.output["facts_preserved"])
    if operation == "polish":
        assert len(receipt.output["text"].removeprefix("【草稿】")) <= len(original) * 2


@pytest.mark.asyncio
async def test_meeting_minutes_traceability_and_redaction(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    source = root / "weekly.txt"
    source.write_text(
        "张三：确认本周完成接口。\n李四：我负责测试，截止周五。\n王五：不同意当前排期，建议待定。\n张三：决定下周发布。",
        encoding="utf-8",
    )
    tool = MeetingNotesTool([root], tmp_path / "output", DataClassificationService())
    receipt = await tool.execute({"source_path": str(source)})
    output = Path(receipt.output["output_path"])
    markdown = output.read_text(encoding="utf-8")
    assert "## 主要讨论点" in markdown
    assert "## 行动项" in markdown
    assert "[来源：L" in markdown
    assert receipt.output["actions"] >= 1
