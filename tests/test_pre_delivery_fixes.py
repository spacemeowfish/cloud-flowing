"""Regression tests for the pre-delivery fix batches A/B/C (FIXPLAN.md)."""

import asyncio
import hashlib
import json
import sqlite3
import sys
import types
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from pydantic import JsonValue

from agent_platform.adapters.notifications import windows_toast
from agent_platform.adapters.structured_response import effective_max_tokens
from agent_platform.api.server import create_app
from agent_platform.config import Settings
from agent_platform.core.errors import ModelError, ModelTimeoutError
from agent_platform.core.model_gateway import ModelGateway
from agent_platform.core.parameter_normalizer import (
    deterministic_pre_route_arguments,
    extract_text_payload,
    normalize_arguments,
)
from agent_platform.core.tool_executor import ToolExecutor
from agent_platform.core.tool_registry import ToolRegistry
from agent_platform.models import (
    INTENT_CLASSIFICATION_SCHEMA,
    INTENT_RESPONSE_SCHEMA,
    MessageRole,
    ModelMessage,
    RiskLevel,
    ToolCall,
    ToolMetadata,
    ToolReceipt,
    build_argument_extraction_schema,
    build_model_acceptance_schema,
)
from agent_platform.tools.reminder_tool import ReminderTool
from agent_platform.tools.vector_store import HashingEmbedder, SQLiteVectorStore
from ruoyi_support import enable_gateway


def _settings(tmp_path, **updates):
    values = {
        "_env_file": None,
        "model_provider": "mock",
        "database_path": tmp_path / "agent.db",
        "audit_dir": tmp_path / "audit",
        "authorized_file_roots": [tmp_path / "files"],
        "knowledge_roots": [tmp_path / "knowledge"],
        "document_roots": [tmp_path / "documents"],
        "meeting_output_dir": tmp_path / "meeting",
        "audit_flush_size": 1,
    }
    values.update(updates)
    return Settings(**values)


async def _wait_for_state(client, task_id, expected, timeout=3.0):
    states = {expected} if isinstance(expected, str) else set(expected)
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        response = await client.get(f"/tasks/{task_id}")
        assert response.status_code == 200
        task = response.json()
        if task["state"] in states:
            return task
        await asyncio.sleep(0.02)
    raise AssertionError(f"task {task_id} did not reach {states}")


# ---------------------------------------------------------------------------
# A1: developer role must inherit admin policy instead of unknown_role.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_task_created_after_developer_login_completes(tmp_path):
    app = create_app(_settings(tmp_path))
    async with app.router.lifespan_context(app):
        gateway = enable_gateway(app)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=gateway.headers()) as client:
            gateway.promote(client)
            created = await client.post("/tasks", json={"text": "提醒我30分钟后喝水"})
            assert created.status_code == 201
            task = await _wait_for_state(client, created.json()["id"], {"completed", "failed"})
            assert task["state"] == "completed", task.get("error")


# ---------------------------------------------------------------------------
# A2: notification failures must not kill scheduler state or loops.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reminder_poll_due_marks_row_notified_when_callback_fails(tmp_path):
    async def broken_callback(reminder):
        raise RuntimeError("toast exploded")

    tool = ReminderTool(tmp_path / "reminders.db", callback=broken_callback)
    past = datetime(2000, 1, 2, tzinfo=tool._parser.timezone)
    tool._connection.execute(
        "INSERT INTO reminders(text, due_at, repeat_rule, status, created_at) VALUES (?, ?, NULL, 'active', ?)",
        ("喝水", "2000-01-01T00:00:00+08:00", "2000-01-01T00:00:00+08:00"),
    )
    tool._connection.commit()

    assert await tool.poll_due(now=past) == 1
    statuses = tool._connection.execute("SELECT status FROM reminders").fetchall()
    assert [row["status"] for row in statuses] == ["notified"]
    assert await tool.poll_due(now=past) == 0
    tool.close()


@pytest.mark.asyncio
async def test_reminder_scheduler_loop_survives_poll_failures(tmp_path, monkeypatch):
    tool = ReminderTool(tmp_path / "reminders.db")
    attempts = {"count": 0}

    async def exploding_poll(now=None):
        attempts["count"] += 1
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(tool, "poll_due", exploding_poll)
    loop = asyncio.create_task(tool._scheduler_loop())
    await asyncio.sleep(1.2)
    assert not loop.done(), "scheduler loop died from a poll failure"
    assert attempts["count"] >= 2
    loop.cancel()
    await asyncio.gather(loop, return_exceptions=True)
    tool.close()


@pytest.mark.asyncio
async def test_windows_toast_failure_falls_back_to_console(caplog, monkeypatch):
    class BrokenNotification:
        def __init__(self, **kwargs):
            pass

        def show(self):
            raise OSError("toast backend unavailable")

    fake_winotify = types.ModuleType("winotify")
    fake_winotify.Notification = BrokenNotification
    monkeypatch.setitem(sys.modules, "winotify", fake_winotify)
    with caplog.at_level("ERROR"):
        await windows_toast({"text": "提醒我喝水"})
    assert any("toast notification failed" in message for message in caplog.messages)


# ---------------------------------------------------------------------------
# A3: knowledge.db must enable WAL and busy_timeout.
# ---------------------------------------------------------------------------


def test_vector_store_enables_wal_and_survives_foreign_write_transaction(tmp_path):
    store = SQLiteVectorStore(tmp_path / "knowledge.db", HashingEmbedder())
    mode = str(store._connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
    assert mode == "wal"
    timeout = int(store._connection.execute("PRAGMA busy_timeout").fetchone()[0])
    assert timeout >= 5000

    other = sqlite3.connect(tmp_path / "knowledge.db")
    other.execute("PRAGMA busy_timeout=5000")
    other.execute("BEGIN IMMEDIATE")
    other.execute("INSERT INTO documents(path, mtime, scope) VALUES ('foreign.txt', 1.0, 's')")
    # Under WAL a reader works on the last committed snapshot instead of
    # failing with "database is locked" while the writer holds the lock.
    assert store.indexed_mtime(Path("foreign.txt")) is None
    other.rollback()
    other.close()


# ---------------------------------------------------------------------------
# B1/B2/B3: staged model pipeline robustness for the 3B demo model.
# ---------------------------------------------------------------------------


def _acceptance_registry(text_max_length: int = 10000) -> ToolRegistry:
    class MetadataTool:
        def __init__(self, name, required, properties):
            self._metadata = ToolMetadata(
                name=name,
                description=name,
                parameters_schema={
                    "type": "object",
                    "properties": properties,
                    "required": required,
                    "additionalProperties": False,
                },
            )

        @property
        def metadata(self):
            return self._metadata

    registry = ToolRegistry()
    specs = {
        "file_open": (["query"], {"query": {"type": "string", "maxLength": 200}}),
        "general_chat": (["text"], {"text": {"type": "string"}}),
        "knowledge_query": (["query"], {"query": {"type": "string"}}),
        "meeting_process": (["source_path"], {"source_path": {"type": "string"}}),
        "reminder_create": (["action"], {"action": {"type": "string"}}),
        "todo_manage": (["action"], {"action": {"type": "string"}}),
        "schedule_manage": (["action"], {"action": {"type": "string"}}),
        "text_polish": (
            ["operation", "text"],
            {"operation": {"type": "string"}, "text": {"type": "string", "maxLength": text_max_length}},
        ),
    }
    for name, (required, properties) in specs.items():
        registry.register(MetadataTool(name, required, properties))  # type: ignore[arg-type]
    registry.freeze()
    return registry


def test_effective_max_tokens_relaxes_only_argument_extraction():
    acceptance = build_model_acceptance_schema(_acceptance_registry())
    extraction = build_argument_extraction_schema(acceptance, "text_polish")
    assert effective_max_tokens(extraction, 512) == 512
    assert effective_max_tokens(extraction, 4096) == 512
    assert effective_max_tokens(extraction, 512, extraction_limit=768) == 512
    assert effective_max_tokens(INTENT_CLASSIFICATION_SCHEMA, 512) == 192
    assert effective_max_tokens(INTENT_RESPONSE_SCHEMA, 512) == 192


class _ScriptedAdapter:
    """Return canned results or exceptions, recording every call."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    async def generate(self, messages, response_schema, max_tokens=512):
        self.calls.append((list(messages), response_schema))
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_interpret_regenerates_once_after_truncated_json():
    # The request avoids the "润色：" pre-route prefix so both stages go to
    # the (scripted) model.
    long_payload = "预算说明" * 40
    adapter = _ScriptedAdapter(
        [
            {"intent": "text_polish", "confidence": 0.9},
            ModelError("Ollama model returned invalid structured JSON"),
            {"arguments": {"operation": "polish", "text": long_payload}, "missing_fields": []},
        ]
    )
    gateway = ModelGateway(adapter)
    result = await gateway.interpret(
        "这段文字帮我润色一下", build_model_acceptance_schema(_acceptance_registry())
    )
    assert result.intent.arguments["text"] == long_payload
    assert result.model_calls == 3
    assert result.schema_repaired is True


@pytest.mark.asyncio
async def test_interpret_repairs_classification_with_extra_fields():
    adapter = _ScriptedAdapter(
        [
            {"intent": "knowledge_query", "confidence": 0.9, "arguments": {"query": "x"}},
            {"intent": "knowledge_query", "confidence": 0.9},
            {"arguments": {"query": "这段材料讲了什么"}, "missing_fields": []},
        ]
    )
    gateway = ModelGateway(adapter)
    result = await gateway.interpret(
        "帮我处理一下这段材料", build_model_acceptance_schema(_acceptance_registry())
    )
    assert result.intent.intent == "knowledge_query"
    assert result.model_calls == 3
    assert result.schema_repaired is True
    assert "不得包含 arguments" in adapter.calls[1][0][-1].content


@pytest.mark.asyncio
async def test_interpret_falls_back_to_model_when_deterministic_args_exceed_schema():
    long_payload = "很长的原文" * 3000  # 15000 chars, clamped to 10000 by the payload helper
    request = "润色：" + long_payload
    deterministic = deterministic_pre_route_arguments("text_polish", request)
    assert deterministic is not None and len(str(deterministic["text"])) == 10000

    # A tighter schema limit (5000) makes the deterministic arguments invalid,
    # so the gateway must consult the model instead of failing the task.
    adapter = _ScriptedAdapter(
        [{"arguments": {"operation": "polish", "text": long_payload[:4000]}, "missing_fields": []}]
    )
    gateway = ModelGateway(adapter)
    result = await gateway.interpret(request, build_model_acceptance_schema(_acceptance_registry(text_max_length=5000)))
    assert result.route_source == "pre_route:text_operation_prefix"
    assert result.model_calls == 1
    assert result.intent.arguments == {"operation": "polish", "text": long_payload[:4000]}


def test_schedule_start_text_uses_time_cue_and_bounded_title_fallback():
    long_description = "讨论新版发布节奏与灰度方案" * 20
    request = f"预约A301会议室明天下午3点{long_description}"
    result = normalize_arguments(
        intent="schedule_manage",
        arguments={"action": "create", "title": "", "start_text": "下周"},
        request_text=request,
    )
    assert result.arguments["start_text"] == "明天下午3点"
    assert len(str(result.arguments["start_text"])) <= 200
    assert result.arguments["title"] == f"A301会议室{long_description}"[:200]
    assert result.applied_rules == [
        "schedule_manage.start_text_from_request",
        "schedule_manage.title_from_request",
    ]


def test_schedule_start_text_is_truncated_to_schema_limit():
    filler = "补充说明" * 60  # 240 chars after the time cue
    result = normalize_arguments(
        intent="schedule_manage",
        arguments={"action": "create", "title": "例会"},
        request_text=f"明天下午3点{filler}",
    )
    assert len(str(result.arguments.get("start_text", ""))) <= 200


def test_text_polish_payload_is_clamped_to_schema_limit():
    request = "润色：" + "超长文本" * 4000  # 16000 chars
    payload = extract_text_payload(request)
    assert len(payload) == 10000

    result = normalize_arguments(
        intent="text_polish",
        arguments={"operation": "polish", "text": "超长文本" * 4000},
        request_text=request,
    )
    assert len(str(result.arguments["text"])) == 10000
    assert "text_polish.clamp_text_length" in result.applied_rules


# ---------------------------------------------------------------------------
# B4: transient connection errors retry once; timeouts do not.
# ---------------------------------------------------------------------------


class _FlakyAdapter:
    def __init__(self, failures, error):
        self.failures = failures
        self.error = error
        self.calls = 0

    async def generate(self, messages, response_schema, max_tokens=512):
        del messages, response_schema, max_tokens
        self.calls += 1
        if self.calls <= self.failures:
            raise self.error
        return {"ok": True}

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_gateway_retries_one_transient_connection_error():
    adapter = _FlakyAdapter(1, ModelError("Ollama model connection failed", retryable=True))
    gateway = ModelGateway(adapter)
    result = await gateway.generate([ModelMessage(role=MessageRole.USER, content="x")], {"type": "object"})
    assert result == {"ok": True}
    assert adapter.calls == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [ModelError("connection failed", retryable=True), ModelTimeoutError("timed out")])
async def test_gateway_gives_up_quickly_when_model_stays_down(error):
    class AlwaysDown:
        def __init__(self):
            self.calls = 0

        async def generate(self, messages, response_schema, max_tokens=512):
            del messages, response_schema, max_tokens
            self.calls += 1
            raise error

        async def close(self):
            return None

    adapter = AlwaysDown()
    gateway = ModelGateway(adapter)
    with pytest.raises(ModelError):
        await gateway.generate([ModelMessage(role=MessageRole.USER, content="x")], {"type": "object"})
    expected_calls = 2 if error.retryable and not isinstance(error, ModelTimeoutError) else 1
    assert adapter.calls == expected_calls


# ---------------------------------------------------------------------------
# C1: queue routing fails honestly instead of parking in waiting_network.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_offline_throttled_task_fails_with_readable_error(tmp_path):
    app = create_app(_settings(tmp_path, network_available=False, resource_mode="throttled"))
    async with app.router.lifespan_context(app):
        gateway = enable_gateway(app)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=gateway.headers()) as client:
            created = await client.post("/tasks", json={"text": "提醒我30分钟后喝水"})
            task = await _wait_for_state(client, created.json()["id"], {"failed", "waiting_network"})
            assert task["state"] == "failed"
            assert "离线" in str(task.get("error"))


# ---------------------------------------------------------------------------
# C2: admin reindex reuses the container's live knowledge tool roots.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_reindex_uses_document_roots_of_live_tool(tmp_path, monkeypatch):
    documents = tmp_path / "documents"
    documents.mkdir(parents=True)
    (documents / "warranty.txt").write_text("云湃设备保修期是两年。", encoding="utf-8")
    legacy = tmp_path / "knowledge"
    legacy.mkdir()
    # AGENT_DOCUMENT_ROOTS is the canonical source and must win over the
    # legacy knowledge_roots value below.
    monkeypatch.setenv("AGENT_DOCUMENT_ROOTS", json.dumps([str(documents)]))
    app = create_app(_settings(tmp_path, knowledge_roots=[legacy]))
    async with app.router.lifespan_context(app):
        gateway = enable_gateway(app)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=gateway.headers()) as client:
            gateway.promote(client)
            response = await client.post("/admin/knowledge/reindex")
            assert response.status_code == 200
            report = response.json()
            assert report["scanned"] >= 1
            # The file exists only under document_roots (the live tool's
            # roots); the legacy knowledge_roots directory stays empty, so a
            # hit proves the reindex reused the container instance.
            created = await client.post("/tasks", json={"text": "查询云湃设备保修期"})
            task = await _wait_for_state(client, created.json()["id"], "completed")
            assert "两年" in json.dumps(task.get("result", {}), ensure_ascii=False)


# ---------------------------------------------------------------------------
# C3: mutation idempotency uses a shorter TTL than read-like receipts.
# ---------------------------------------------------------------------------


class _CountingStateTool:
    def __init__(self, key_prefix, tool_name):
        self.key_prefix = key_prefix
        self.tool_name = tool_name
        self.count = 0

    @property
    def metadata(self):
        return ToolMetadata(
            name=self.tool_name,
            description="counter",
            parameters_schema={
                "type": "object",
                "properties": {"value": {"type": "integer"}},
                "required": ["value"],
                "additionalProperties": False,
            },
            risk_level=RiskLevel.R0,
        )

    def idempotency_key(self, arguments: dict[str, JsonValue]) -> str:
        digest = hashlib.sha256(json.dumps(arguments, sort_keys=True).encode()).hexdigest()
        return f"{self.key_prefix}:{digest}"

    async def execute(self, arguments, context=None):
        self.count += 1
        return ToolReceipt(
            tool_name=self.tool_name, actual_arguments=arguments, success=True, output_summary="ok"
        )


@pytest.mark.asyncio
async def test_mutation_receipts_expire_quickly_while_reads_stay_cached():
    mutation = _CountingStateTool("mutation:reminder", "counting_mutation")
    read_like = _CountingStateTool("reminder", "counting_read")
    registry = ToolRegistry()
    registry.register(mutation)
    registry.register(read_like)
    registry.freeze()
    executor = ToolExecutor(
        registry,
        idempotency_ttl_seconds=3600,
        mutation_idempotency_ttl_seconds=0,
    )
    call = ToolCall(
        task_id="00000000-0000-0000-0000-000000000001",
        tool_name=mutation.tool_name,
        arguments={"value": 1},
    )
    await executor.execute(call)
    await executor.execute(call)
    assert mutation.count == 2  # mutation TTL expired immediately

    read_call = ToolCall(
        task_id="00000000-0000-0000-0000-000000000002",
        tool_name=read_like.tool_name,
        arguments={"value": 1},
    )
    await executor.execute(read_call)
    await executor.execute(read_call)
    assert read_like.count == 1  # read-like cache holds


def test_state_changing_tools_prefix_mutation_keys(tmp_path):
    tool = ReminderTool(tmp_path / "reminders.db")
    assert tool.idempotency_key({"action": "create", "text": "喝水", "when": "30分钟后"}).startswith("mutation:")
    assert not tool.idempotency_key({"action": "query"}).startswith("mutation:")
    tool.close()


# ---------------------------------------------------------------------------
# C4: cancel is idempotent on terminal tasks.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_completed_task_returns_current_record(tmp_path):
    app = create_app(_settings(tmp_path))
    async with app.router.lifespan_context(app):
        gateway = enable_gateway(app)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=gateway.headers()) as client:
            created = await client.post("/tasks", json={"text": "1+1等于多少？"})
            task_id = created.json()["id"]
            await _wait_for_state(client, task_id, "completed")
            cancelled = await client.post(f"/tasks/{task_id}/cancel", json={"reason": "late"})
            assert cancelled.status_code == 200
            assert cancelled.json()["state"] == "completed"
