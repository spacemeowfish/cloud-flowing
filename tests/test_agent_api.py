import asyncio
from pathlib import Path

import httpx
import pytest

from agent_platform.adapters.mock_adapter import MockModelAdapter
from agent_platform.api.server import create_app
from agent_platform.config import Settings
from agent_platform.core.model_gateway import ModelGateway
from agent_platform.models import TaskState


class _DateDroppingReminderAdapter(MockModelAdapter):
    async def generate(self, messages, response_schema, max_tokens=512):
        if "intent" in response_schema.get("properties", {}) and messages[-1].content == "提醒我明天开会":
            return {
                "intent": "reminder_create",
                "arguments": {"action": "create", "text": "开会"},
                "missing_fields": ["when"],
                "confidence": 1.0,
            }
        return await super().generate(messages, response_schema, max_tokens)


class _TextOptionalMissingAdapter(MockModelAdapter):
    async def generate(self, messages, response_schema, max_tokens=512):
        text = messages[-1].content
        if text == "总结这段：项目将在2026年8月1日上线，预算为300万元。":
            return {
                "arguments": {
                    "operation": "summarize",
                    "text": "项目将在2026年8月1日上线，预算为300万元。",
                },
                "missing_fields": ["target_length"],
            }
        if text == "调整为轻松语气：项目将在2026年8月1日上线，预算为300万元。":
            return {
                "arguments": {
                    "operation": "tone_adjust",
                    "text": "项目将在2026年8月1日上线，预算为300万元。",
                    "tone": "casual",
                },
                "missing_fields": ["tone"],
            }
        return await super().generate(messages, response_schema, max_tokens)


async def _wait_for_state(client, task_id, expected, timeout=2.0):
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


def _settings(tmp_path):
    allowed = tmp_path / "allowed"
    knowledge = tmp_path / "knowledge"
    allowed.mkdir()
    knowledge.mkdir()
    (knowledge / "warranty.txt").write_text("X 产品保修期是三年。", encoding="utf-8")
    return Settings(
        model_provider="mock",
        database_path=tmp_path / "agent.db",
        audit_dir=tmp_path / "audit",
        authorized_file_roots=[allowed],
        knowledge_roots=[knowledge],
        meeting_output_dir=tmp_path / "meeting",
        audit_flush_size=1,
        developer_password="test-developer-password",
    )


async def _developer_login(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/auth/developer/login", json={"password": "test-developer-password"}
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_api_task_audit_errors_and_openapi(tmp_path):
    app = create_app(_settings(tmp_path))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post("/tasks", json={"text": "查询X产品保修期"})
            assert created.status_code == 201
            task = created.json()
            assert task["state"] == TaskState.RECEIVED.value
            task_id = task["id"]
            task = await _wait_for_state(client, task_id, TaskState.COMPLETED.value)
            queried = await client.get(f"/tasks/{task_id}")
            assert queried.status_code == 200
            assert (await client.get(f"/tasks/{task_id}/audit")).status_code == 403
            await _developer_login(client)
            audit = await client.get(f"/tasks/{task_id}/audit")
            assert audit.status_code == 200
            assert len(audit.json()) >= 7
            missing = await client.get("/tasks/00000000-0000-0000-0000-000000000001")
            assert missing.status_code == 404
            assert missing.json()["code"] == "task_not_found"
            invalid = await client.post("/tasks", json={"text": ""})
            assert invalid.status_code == 422
            assert invalid.json()["code"] == "request_validation_error"
            docs = await client.get("/openapi.json")
            assert docs.status_code == 200
            assert "/tasks/{task_id}/events" in docs.json()["paths"]
            assert "/meta/capabilities" in docs.json()["paths"]

            history = await client.get("/tasks")
            assert history.status_code == 200
            assert history.json()[0]["id"] == task_id

            capabilities = await client.get("/meta/capabilities")
            assert capabilities.status_code == 200
            capability_payload = capabilities.json()
            assert {tool["name"] for tool in capability_payload["tools"]} == {
                "file_open",
                "general_chat",
                "knowledge_query",
                "reminder_create",
                "todo_manage",
                "schedule_manage",
                "text_polish",
                "meeting_process",
            }
            assert capability_payload["safety"]["secret_values_exposed"] is False


@pytest.mark.asyncio
async def test_meeting_confirmation_and_cancel(tmp_path):
    settings = _settings(tmp_path)
    source = settings.authorized_file_roots[0] / "meeting.txt"
    source.write_text("张三：决定发布。\n李四：我负责测试。", encoding="utf-8")
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post("/tasks", json={"text": f"整理会议纪要 {source}"})
            task_id = created.json()["id"]
            await _wait_for_state(client, task_id, TaskState.AWAITING_CONFIRMATION.value)
            confirmed = await client.post(f"/tasks/{task_id}/confirm", json={"approved": True, "arguments": {}})
            assert confirmed.status_code == 200
            assert confirmed.json()["state"] == TaskState.COMPLETED.value

            second = await client.post("/tasks", json={"text": f"整理会议纪要 {source}"})
            await _wait_for_state(client, second.json()["id"], TaskState.AWAITING_CONFIRMATION.value)
            cancelled = await client.post(
                f"/tasks/{second.json()['id']}/cancel", json={"reason": "test_cancel"}
            )
            assert cancelled.json()["state"] == TaskState.CANCELLED.value


@pytest.mark.asyncio
async def test_session_isolation(tmp_path):
    app = create_app(_settings(tmp_path))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as owner, httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as other:
            created = await owner.post("/tasks", json={"text": "查询产品", "session_id": "forged"})
            task_id = created.json()["id"]
            forbidden = await other.get(f"/tasks/{task_id}", headers={"X-Session-Id": "forged"})
            assert forbidden.status_code == 403
            visible = await owner.get("/tasks")
            hidden = await other.get("/tasks")
            assert [task["id"] for task in visible.json()] == [task_id]
            assert hidden.json() == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "request_text",
    [
        "润色：项目将在2026年8月1日上线",
        "总结这段：本季度完成了三个项目",
        "调整语气：请尽快提交材料",
        "草拟：通知大家明天开会",
    ],
)
async def test_text_operations_complete_through_agent_and_real_tool_executor(tmp_path, request_text):
    app = create_app(_settings(tmp_path))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post("/tasks", json={"text": request_text})
            task = await _wait_for_state(client, created.json()["id"], TaskState.COMPLETED.value)
            assert task["result"]["tool_name"] == "text_polish"
            assert not task["result"]["output"]["text"].startswith("【草稿】")
            if "2026年8月1日" in request_text:
                assert "2026年8月1日" in task["result"]["output"]["text"]


@pytest.mark.asyncio
async def test_text_optional_missing_fields_do_not_stop_processing_at_confirmation_gate(tmp_path):
    app = create_app(_settings(tmp_path))
    async with app.router.lifespan_context(app):
        gateway = ModelGateway(_TextOptionalMissingAdapter())
        app.state.container.gateway = gateway
        app.state.container.agent._gateway = gateway
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            for request_text in (
                "总结这段：项目将在2026年8月1日上线，预算为300万元。",
                "调整为轻松语气：项目将在2026年8月1日上线，预算为300万元。",
            ):
                created = await client.post("/tasks", json={"text": request_text})
                task = await _wait_for_state(client, created.json()["id"], TaskState.COMPLETED.value)
                assert task["result"]["tool_name"] == "text_polish"
                assert task["result"]["output"]["text"]


@pytest.mark.asyncio
async def test_forged_session_header_is_ignored_and_d3_never_persisted(tmp_path):
    settings = _settings(tmp_path)
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post(
                "/tasks",
                json={"text": "查询 password=abc123", "session_id": "payload-session"},
                headers={"X-Session-Id": "header-session"},
            )
            payload = created.json()
            assert payload["session_id"] not in {"header-session", "payload-session", "default"}
            assert "abc123" not in payload["request_text"]
            database_files = [
                settings.database_path,
                Path(str(settings.database_path) + "-wal"),
                Path(str(settings.database_path) + "-shm"),
            ]
            persisted = b"".join(path.read_bytes() for path in database_files if path.exists())
            assert b"abc123" not in persisted


@pytest.mark.asyncio
async def test_static_web_and_three_confirmation_flows(tmp_path):
    settings = _settings(tmp_path)
    allowed = settings.authorized_file_roots[0]
    (allowed / "项目周报_本周.txt").write_text("本周完成接口联调。", encoding="utf-8")
    (allowed / "项目周报_上周.txt").write_text("上周完成需求评审。", encoding="utf-8")
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            page = await client.get("/")
            assert page.status_code == 200
            assert "云湃 AI" in page.text
            assert "接口测试中心" not in page.text
            assert "developerEntry" in page.text
            assert (await client.get("/developer", follow_redirects=False)).status_code == 303
            await _developer_login(client)
            developer_page = await client.get("/developer")
            assert developer_page.status_code == 200
            assert "接口测试中心" in developer_page.text
            await client.post("/auth/logout")
            script = await client.get("/app.js")
            assert script.status_code == 200
            assert "EventSource" in script.text

            file_task = (await client.post("/tasks", json={"text": "打开项目周报"})).json()
            file_task = await _wait_for_state(client, file_task["id"], TaskState.AWAITING_CONFIRMATION.value)
            candidates = file_task["result"]["receipt"]["output"]["candidates"]
            assert len(candidates) == 2
            file_done = await client.post(
                f"/tasks/{file_task['id']}/confirm",
                json={"approved": True, "arguments": {"selected_path": candidates[0]["path"]}},
            )
            assert file_done.json()["state"] == TaskState.COMPLETED.value

            replacement_gateway = ModelGateway(_DateDroppingReminderAdapter())
            app.state.container.gateway = replacement_gateway
            app.state.container.agent._gateway = replacement_gateway
            reminder = (await client.post("/tasks", json={"text": "提醒我明天开会"})).json()
            reminder = await _wait_for_state(client, reminder["id"], TaskState.AWAITING_CONFIRMATION.value)
            assert reminder["result"]["type"] == "missing_fields"
            assert reminder["result"]["fields"] == ["when"]
            reminder_done = await client.post(
                f"/tasks/{reminder['id']}/confirm",
                json={"approved": True, "arguments": {"when": "15:00"}},
            )
            assert reminder_done.json()["state"] == TaskState.COMPLETED.value

            delete_task = (await client.post("/tasks", json={"text": "删除全部提醒"})).json()
            delete_task = await _wait_for_state(client, delete_task["id"], TaskState.AWAITING_CONFIRMATION.value)
            assert delete_task["risk_level"] == "R3"
            assert delete_task["result"]["type"] == "risk_confirmation"
            rejected = await client.post(
                f"/tasks/{delete_task['id']}/confirm",
                json={"approved": False, "arguments": {}},
            )
            assert rejected.json()["state"] == TaskState.CANCELLED.value
            await _developer_login(client)
            audit = (await client.get(f"/tasks/{delete_task['id']}/audit")).json()
            assert any(event["event_type"] == "confirmation_rejected" for event in audit)
