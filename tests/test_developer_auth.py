import logging

import httpx
import pytest
from pydantic import ValidationError

from agent_platform.api.server import create_app
from agent_platform.config import Settings
from agent_platform.core.recent_logs import RecentLogHandler, sanitize_log_message


def _settings(tmp_path, **updates):
    values = {
        "_env_file": None,
        "model_provider": "mock",
        "database_path": tmp_path / "agent.db",
        "audit_dir": tmp_path / "audit",
        "authorized_file_roots": [tmp_path / "files"],
        "knowledge_roots": [tmp_path / "knowledge"],
        "meeting_output_dir": tmp_path / "meeting",
        "developer_password": "correct horse battery staple",
    }
    values.update(updates)
    return Settings(**values)


@pytest.mark.asyncio
async def test_developer_login_protects_internal_routes_and_ignores_role_header(tmp_path):
    app = create_app(_settings(tmp_path))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            assert (await client.get("/auth/me")).json()["role"] == "user"
            created = await client.post("/tasks", json={"text": "1+1等于多少？"})
            assert created.status_code == 201
            task_id = created.json()["id"]
            forged = await client.get("/meta/capabilities", headers={"X-Agent-Role": "developer"})
            assert forged.status_code == 403
            assert (await client.post("/auth/developer/login", json={"password": "wrong"})).status_code == 401
            login = await client.post(
                "/auth/developer/login", json={"password": "correct horse battery staple"}
            )
            assert login.status_code == 200
            assert login.json()["role"] == "developer"
            assert "HttpOnly" in login.headers["set-cookie"]
            assert (await client.get("/meta/capabilities")).status_code == 200
            assert (await client.get("/openapi.json")).status_code == 200
            assert (await client.get("/admin/settings")).status_code == 200
            assert (await client.get(f"/tasks/{task_id}")).status_code == 200
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as other:
                await other.post(
                    "/auth/developer/login", json={"password": "correct horse battery staple"}
                )
                assert (await other.get(f"/tasks/{task_id}")).status_code == 403
            assert (await client.post("/auth/logout")).status_code == 200
            assert (await client.get("/meta/capabilities")).status_code == 403


@pytest.mark.asyncio
async def test_developer_session_is_invalid_after_service_restart(tmp_path):
    settings = _settings(tmp_path)
    first_app = create_app(settings)
    async with first_app.router.lifespan_context(first_app):
        first_transport = httpx.ASGITransport(app=first_app)
        async with httpx.AsyncClient(transport=first_transport, base_url="http://test") as client:
            await client.post(
                "/auth/developer/login", json={"password": "correct horse battery staple"}
            )
            cookies = dict(client.cookies)
    second_app = create_app(settings)
    async with second_app.router.lifespan_context(second_app):
        second_transport = httpx.ASGITransport(app=second_app)
        async with httpx.AsyncClient(
            transport=second_transport, base_url="http://test", cookies=cookies
        ) as client:
            assert (await client.get("/auth/me")).json()["role"] == "user"
            assert (await client.get("/developer/logs")).status_code == 403


def test_lan_binding_requires_developer_password(tmp_path):
    with pytest.raises(ValidationError, match="DEVELOPER_PASSWORD"):
        _settings(tmp_path, host="0.0.0.0", developer_password="")
    assert _settings(tmp_path, host="0.0.0.0").host == "0.0.0.0"
    assert _settings(tmp_path, host="127.0.0.1", developer_password="").host == "127.0.0.1"


def test_recent_log_handler_is_bounded_and_redacts_sensitive_values():
    handler = RecentLogHandler(capacity=3, secrets=("dev-pass",))
    for index in range(5):
        record = logging.LogRecord(
            "agent_platform.test",
            logging.INFO,
            __file__,
            1,
            f"password=dev-pass cookie=session C:\\secret\\file.txt request_text=private-{index}",
            (),
            None,
        )
        handler.emit(record)
    items = handler.recent()
    assert len(items) == 3
    combined = " ".join(item["message"] for item in items)
    assert "private-" not in combined
    assert "dev-pass" not in combined
    assert "session" not in combined
    assert "C:\\secret" not in combined
    assert "[REDACTED]" in combined
    assert "[LOCAL_PATH]" in combined
    assert sanitize_log_message("api_key=abc /home/user/model.bin") == "api_key=[REDACTED] [LOCAL_PATH]"


@pytest.mark.asyncio
async def test_recent_log_endpoint_returns_sanitized_records(tmp_path):
    app = create_app(_settings(tmp_path))
    async with app.router.lifespan_context(app):
        logging.getLogger("agent_platform.test").warning(
            "password=correct horse battery staple request_text=private task C:\\Users\\name\\data.txt"
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/auth/developer/login", json={"password": "correct horse battery staple"}
            )
            payload = (await client.get("/developer/logs")).json()
            assert payload["count"] <= payload["limit"] == 200
            text = str(payload)
            assert "correct horse battery staple" not in text
            assert "private task" not in text
            assert "C:\\Users\\name" not in text
