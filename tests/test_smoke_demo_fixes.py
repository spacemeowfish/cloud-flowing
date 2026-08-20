"""Regression tests for the manual smoke defect fixes S1-S8 (SMOKE-FIXPLAN.md)."""

import asyncio
from pathlib import Path

import httpx
import pytest
from pydantic import JsonValue

from agent_platform.adapters.platform import DisabledFileOpener
from agent_platform.api.server import create_app
from agent_platform.config import Settings
from agent_platform.tools.file_search_tool import FileSearchTool


def _settings(tmp_path, **updates):
    values = {
        "_env_file": None,
        "model_provider": "mock",
        "database_path": tmp_path / "agent.db",
        "audit_dir": tmp_path / "audit",
        # 只设置 document_roots：同时显式设置 legacy 的 authorized_file_roots/
        # knowledge_roots 会触发 settings 校验器用 legacy 值覆盖 document_roots。
        "document_roots": [tmp_path / "documents"],
        "meeting_output_dir": tmp_path / "meeting",
        "developer_password": "dev-pass-123",
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
# S6: disabled file opener must be reported honestly.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_file_open_reports_disabled_configuration(tmp_path):
    root = tmp_path / "documents"
    root.mkdir()
    target = root / "会议纪要_需求评审.txt"
    target.write_text("内容", encoding="utf-8")
    tool = FileSearchTool([root], DisabledFileOpener())

    receipt = await tool.execute({"query": "会议纪要", "selected_path": str(target)})

    assert receipt.success is True
    assert receipt.output["process_status"] == "disabled_by_configuration"
    assert "已在配置中禁用" in receipt.output_summary
    assert "AGENT_FILE_OPEN_ENABLED=false" in receipt.output_summary
    assert "文件处理完成" not in receipt.output_summary


@pytest.mark.asyncio
async def test_file_open_summary_unchanged_when_opener_active(tmp_path):
    class _ActiveOpener:
        async def open(self, path):
            return {"path": str(path), "process_status": "shell_request_accepted"}

    root = tmp_path / "documents"
    root.mkdir()
    target = root / "会议纪要_需求评审.txt"
    target.write_text("内容", encoding="utf-8")
    tool = FileSearchTool([root], _ActiveOpener())

    receipt = await tool.execute({"query": "会议纪要", "selected_path": str(target)})

    assert receipt.success is True
    assert receipt.output_summary == f"文件处理完成：{target.name}"


# ---------------------------------------------------------------------------
# S8: zero-hit file search must degrade instead of returning nothing.
# ---------------------------------------------------------------------------


def _weekly_report_root(tmp_path):
    root = tmp_path / "documents"
    root.mkdir()
    names = [
        "项目周报_20260714.txt",
        "项目周报_20260721.txt",
        "项目周报_20260728.txt",
        "项目周报_20260804.txt",
        "项目周报模板.txt",
        "IT安全规范.md",
    ]
    for name in names:
        (root / name).write_text("内容", encoding="utf-8")
    return root


def test_search_degrades_modified_keyword_to_hits(tmp_path):
    root = _weekly_report_root(tmp_path)
    tool = FileSearchTool([root], DisabledFileOpener())

    hits = tool.search("这周的项目周报")

    assert {Path(hit["path"]).name for hit in hits} == {
        "项目周报_20260714.txt",
        "项目周报_20260721.txt",
        "项目周报_20260728.txt",
        "项目周报_20260804.txt",
        "项目周报模板.txt",
    }


def test_search_whole_sentence_wrapper_fallback(tmp_path):
    root = _weekly_report_root(tmp_path)
    tool = FileSearchTool([root], DisabledFileOpener())

    hits = tool.search("帮我找一下周报")

    assert len(hits) == 5
    assert all("周报" in Path(hit["path"]).name for hit in hits)


def test_search_bare_keyword_hits_unchanged(tmp_path):
    root = _weekly_report_root(tmp_path)
    tool = FileSearchTool([root], DisabledFileOpener())

    hits = tool.search("周报")
    bare_names = [Path(hit["path"]).name for hit in hits]

    assert len(bare_names) == 5
    assert "IT安全规范.md" not in bare_names
    degraded = tool.search("这周的项目周报")
    assert [Path(hit["path"]).name for hit in degraded] == bare_names


def test_search_bigram_fallback_matches_scattered_pairs(tmp_path):
    root = tmp_path / "documents"
    root.mkdir()
    (root / "分级据分数据.txt").write_text("内容", encoding="utf-8")
    (root / "会议纪要_需求评审.txt").write_text("内容", encoding="utf-8")
    tool = FileSearchTool([root], DisabledFileOpener())

    # 顺序子序列匹配失败，但全部相邻二元组都在文件名中出现，bigram 兜底应命中。
    hits = tool.search("数据分级")

    assert [Path(hit["path"]).name for hit in hits] == ["分级据分数据.txt"]


# ---------------------------------------------------------------------------
# S4: missing required tool arguments must become a Chinese clarification gate.
# ---------------------------------------------------------------------------


class _ScriptedAdapter:
    """Return canned results, recording every call."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    async def generate(self, messages, response_schema, max_tokens=512):
        self.calls.append(list(messages))
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_booking_without_time_asks_for_start_text_in_chinese(tmp_path):
    app = create_app(_settings(tmp_path))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post("/tasks", json={"text": "帮我预约下会议室"})
            assert created.status_code == 201
            task = await _wait_for_state(client, created.json()["id"], "awaiting_confirmation")
            result = task["result"]
            assert result["type"] == "missing_fields"
            assert "start_text" in result["fields"]
            assert "开始时间" in result["message"]
            assert "schema" not in result["message"].lower()

            confirmed = await client.post(
                f"/tasks/{task['id']}/confirm",
                json={"approved": True, "arguments": {"start_text": "明天下午3点"}},
            )
            assert confirmed.status_code == 200
            finished = await _wait_for_state(client, task["id"], {"completed", "failed"})
            assert finished["state"] == "completed", finished.get("error")
            assert "已创建日程" in finished["result"]["output_summary"]
            assert "T15:00:00" in finished["result"]["output"]["item"]["start_at"]


@pytest.mark.asyncio
async def test_booking_with_a_classifier_wording_also_clarifies(tmp_path):
    app = create_app(_settings(tmp_path))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post("/tasks", json={"text": "帮我预约一个会议室"})
            assert created.status_code == 201
            task = await _wait_for_state(client, created.json()["id"], "awaiting_confirmation")
            assert "start_text" in task["result"]["fields"]


@pytest.mark.asyncio
async def test_booking_with_full_time_still_completes(tmp_path):
    app = create_app(_settings(tmp_path))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post("/tasks", json={"text": "添加日程 项目评审会 明天下午3点"})
            assert created.status_code == 201
            task = await _wait_for_state(client, created.json()["id"], {"completed", "failed"})
            assert task["state"] == "completed", task.get("error")


@pytest.mark.asyncio
async def test_model_path_missing_start_text_becomes_chinese_gate(tmp_path, monkeypatch):
    from agent_platform.core.model_gateway import ModelGateway

    adapter = _ScriptedAdapter(
        [
            {"intent": "schedule_manage", "confidence": 0.9},
            {"arguments": {"action": "create", "title": "项目评审会"}, "missing_fields": []},
        ]
    )
    scripted = ModelGateway(adapter)
    monkeypatch.setattr(
        ModelGateway, "from_settings", classmethod(lambda cls, settings: scripted)
    )
    app = create_app(_settings(tmp_path))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post("/tasks", json={"text": "帮团队预约一次项目评审时间再定"})
            assert created.status_code == 201
            task = await _wait_for_state(client, created.json()["id"], "awaiting_confirmation")
            result = task["result"]
            assert result["type"] == "missing_fields"
            assert result["fields"] == ["start_text"]
            assert result["message"] == "请补充开始时间，例如：明天下午3点"

            confirmed = await client.post(
                f"/tasks/{task['id']}/confirm",
                json={"approved": True, "arguments": {"start_text": "明天下午3点"}},
            )
            assert confirmed.status_code == 200
            finished = await _wait_for_state(client, task["id"], {"completed", "failed"})
            assert finished["state"] == "completed", finished.get("error")


def test_schema_error_derivation_rejects_non_missing_errors():
    from jsonschema import Draft202012Validator

    from agent_platform.core.agent_core import _missing_fields_from_schema_errors

    schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string"},
            "title": {"type": "string", "minLength": 1},
            "start_text": {"type": "string", "minLength": 1},
            "weekdays": {"type": "array", "items": {"type": "integer"}, "uniqueItems": True},
        },
        "required": ["action"],
        "allOf": [
            {
                "if": {"properties": {"action": {"const": "create"}}, "required": ["action"]},
                "then": {"required": ["title", "start_text"]},
            }
        ],
        "additionalProperties": False,
    }
    missing = list(
        Draft202012Validator(schema).iter_errors({"action": "create", "title": "项目评审会"})
    )
    assert _missing_fields_from_schema_errors(missing) == ["start_text"]

    empty_title = list(
        Draft202012Validator(schema).iter_errors(
            {"action": "create", "title": "", "start_text": "明天下午3点"}
        )
    )
    assert _missing_fields_from_schema_errors(empty_title) == ["title"]

    duplicate_days = list(
        Draft202012Validator(schema).iter_errors(
            {"action": "create", "title": "会", "start_text": "明天下午3点", "weekdays": [1, 1]}
        )
    )
    assert _missing_fields_from_schema_errors(duplicate_days) is None


# ---------------------------------------------------------------------------
# S7: schedule presence queries must route deterministically.
# ---------------------------------------------------------------------------


def test_presence_query_routes_to_schedule_with_today_range():
    from agent_platform.core.intent_router import pre_route_intent
    from agent_platform.core.parameter_normalizer import (
        deterministic_pre_route_arguments,
        normalize_arguments,
    )

    decision = pre_route_intent("帮我查一下今天有没有会议")
    assert decision is not None
    assert decision.intent == "schedule_manage"
    assert decision.rule == "schedule_presence_query"

    arguments = deterministic_pre_route_arguments("schedule_manage", "帮我查一下今天有没有会议")
    assert arguments == {"action": "query", "range": "today"}
    normalized = normalize_arguments(
        intent="schedule_manage", arguments=arguments, request_text="帮我查一下今天有没有会议"
    )
    assert normalized.arguments["range"] == "today"


def test_arrangement_query_wording_keeps_original_rule():
    from agent_platform.core.intent_router import pre_route_intent

    decision = pre_route_intent("今天有什么安排")
    assert decision is not None
    assert decision.intent == "schedule_manage"
    assert decision.rule == "schedule_arrangement_query"


def test_meeting_document_requests_not_hijacked_by_presence_rule():
    from agent_platform.core.intent_router import pre_route_intent

    decision = pre_route_intent("帮我生成数据分级边界讨论稿的会议纪要")
    assert decision is None or decision.rule != "schedule_presence_query"


@pytest.mark.asyncio
async def test_presence_query_returns_honest_empty_result(tmp_path):
    app = create_app(_settings(tmp_path))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post("/tasks", json={"text": "帮我查一下今天有没有会议"})
            assert created.status_code == 201
            task = await _wait_for_state(client, created.json()["id"], {"completed", "failed"})
            assert task["state"] == "completed", task.get("error")
            assert task["result"]["output_summary"] == "查询到 0 个日程实例"
            assert task["context"]["intent"] == "schedule_manage"


# ---------------------------------------------------------------------------
# S2: meeting_process must fuzzy-locate transcripts in authorized roots.
# ---------------------------------------------------------------------------

_MEETING_TRANSCRIPT = (
    "会议时间：2026-08-28 14:00\n与会人：张三、李四\n议题：数据分级边界方案讨论\n"
    "结论：D2 数据默认不出内网。\n"
)


def _meeting_root(tmp_path):
    root = tmp_path / "documents"
    root.mkdir()
    (root / "会前材料_数据分级边界讨论稿_20260828.txt").write_text(
        _MEETING_TRANSCRIPT, encoding="utf-8"
    )
    (root / "项目周报_20260714.txt").write_text("本周完成平台联调。", encoding="utf-8")
    (root / "项目周报_20260721.txt").write_text("本周完成安全评审。", encoding="utf-8")
    (root / "无关文件.txt").write_text("无关内容", encoding="utf-8")
    return root


@pytest.mark.asyncio
async def test_meeting_absolute_path_flow_unchanged(tmp_path):
    root = _meeting_root(tmp_path)
    transcript = root / "会前材料_数据分级边界讨论稿_20260828.txt"
    app = create_app(_settings(tmp_path))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post("/tasks", json={"text": f"整理会议纪要 {transcript}"})
            assert created.status_code == 201
            task = await _wait_for_state(client, created.json()["id"], "awaiting_confirmation")
            assert task["result"]["type"] == "risk_confirmation"

            confirmed = await client.post(
                f"/tasks/{task['id']}/confirm", json={"approved": True, "arguments": {}}
            )
            assert confirmed.status_code == 200
            finished = await _wait_for_state(client, task["id"], {"completed", "failed"})
            assert finished["state"] == "completed", finished.get("error")
            assert "会议纪要已生成" in finished["result"]["output_summary"]


@pytest.mark.asyncio
async def test_meeting_topic_unique_hit_prefills_and_stops_at_r2(tmp_path):
    _meeting_root(tmp_path)
    app = create_app(_settings(tmp_path))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post(
                "/tasks", json={"text": "帮我生成数据分级边界讨论稿的会议纪要"}
            )
            assert created.status_code == 201
            task = await _wait_for_state(client, created.json()["id"], "awaiting_confirmation")
            assert task["risk_level"] == "R2"
            assert task["result"]["type"] == "risk_confirmation"
            assert "会前材料_数据分级边界讨论稿_20260828.txt" in task["result"]["confirmation"][
                "content"
            ]

            confirmed = await client.post(
                f"/tasks/{task['id']}/confirm", json={"approved": True, "arguments": {}}
            )
            assert confirmed.status_code == 200
            finished = await _wait_for_state(client, task["id"], {"completed", "failed"})
            assert finished["state"] == "completed", finished.get("error")
            assert "会议纪要已生成" in finished["result"]["output_summary"]


@pytest.mark.asyncio
async def test_meeting_topic_multiple_hits_use_candidate_gate(tmp_path):
    _meeting_root(tmp_path)
    app = create_app(_settings(tmp_path))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post("/tasks", json={"text": "帮我生成项目周报的会议纪要"})
            assert created.status_code == 201
            task = await _wait_for_state(client, created.json()["id"], "awaiting_confirmation")
            result = task["result"]
            assert result["type"] == "candidate_confirmation"
            candidates = result["receipt"]["output"]["candidates"]
            assert len(candidates) == 2

            confirmed = await client.post(
                f"/tasks/{task['id']}/confirm",
                json={"approved": True, "arguments": {"selected_path": candidates[0]["path"]}},
            )
            assert confirmed.status_code == 200
            finished = await _wait_for_state(client, task["id"], {"completed", "failed"})
            assert finished["state"] == "completed", finished.get("error")
            assert "会议纪要已生成" in finished["result"]["output_summary"]


@pytest.mark.asyncio
async def test_meeting_topic_zero_hits_clarifies(tmp_path):
    _meeting_root(tmp_path)
    app = create_app(_settings(tmp_path))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post("/tasks", json={"text": "帮我生成季度战略复盘的会议纪要"})
            assert created.status_code == 201
            task = await _wait_for_state(client, created.json()["id"], {"completed", "failed"})
            assert task["state"] == "completed", task.get("error")
            assert task["result"]["type"] == "clarification"
            assert task["result"]["message"] == "未在授权目录找到该文稿，请提供完整路径或换个说法"


@pytest.mark.asyncio
async def test_meeting_source_outside_roots_still_rejected(tmp_path):
    _meeting_root(tmp_path)
    outside = tmp_path / "outside_transcript.txt"
    outside.write_text(_MEETING_TRANSCRIPT, encoding="utf-8")
    app = create_app(_settings(tmp_path))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post("/tasks", json={"text": f"整理会议纪要 {outside}"})
            assert created.status_code == 201
            task = await _wait_for_state(client, created.json()["id"], "awaiting_confirmation")
            confirmed = await client.post(
                f"/tasks/{task['id']}/confirm", json={"approved": True, "arguments": {}}
            )
            assert confirmed.status_code == 200
            finished = await _wait_for_state(client, task["id"], {"completed", "failed"})
            assert finished["state"] == "failed"
            assert "PermissionDeniedError" in str(finished["error"])


# ---------------------------------------------------------------------------
# S3: knowledge clarification candidates become clickable suggested questions.
# The frontend template is `项目周报_<8位日期> 的进展内容`; this test pins the
# backend behaviour the template depends on.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clarification_candidates_and_suggested_question_flow(tmp_path):
    root = tmp_path / "documents"
    root.mkdir()
    for date in ("20260714", "20260721", "20260728", "20260804"):
        (root / f"项目周报_{date}.txt").write_text(
            f"{date} 本周完成平台联调与安全评审，风险全部收敛。", encoding="utf-8"
        )
    app = create_app(_settings(tmp_path))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post("/tasks", json={"text": "帮我总结下这次的项目周报"})
            assert created.status_code == 201
            task = await _wait_for_state(client, created.json()["id"], {"completed", "failed"})
            assert task["state"] == "completed", task.get("error")
            result = task["result"]
            assert result["type"] == "clarification"
            assert len(result["candidates"]) == 4
            assert {candidate["date"] for candidate in result["candidates"]} == {
                "2026-07-14",
                "2026-07-21",
                "2026-07-28",
                "2026-08-04",
            }

            # 前端点选候选取 8 位日期拼成建议问句；该问句必须稳定命中对应周报。
            suggested = await client.post("/tasks", json={"text": "项目周报_20260804 的进展内容"})
            assert suggested.status_code == 201
            answered = await _wait_for_state(
                client, suggested.json()["id"], {"completed", "failed"}
            )
            assert answered["state"] == "completed", answered.get("error")
            sources = answered["result"]["output"]["sources"]
            assert [source["file"] for source in sources] == ["项目周报_20260804.txt"]
