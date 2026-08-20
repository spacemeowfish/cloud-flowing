"""Developer authorization under the RuoYi gateway (the password gate retired).

Role comes only from the verified token identity; caller headers never grant
it. Log redaction now masks the shared JWT secret instead of a password.
"""

import logging

import httpx
import pytest

from agent_platform.api.server import create_app
from agent_platform.config import Settings
from agent_platform.core.recent_logs import RecentLogHandler, sanitize_log_message

from ruoyi_support import TEST_JWT_SECRET_B64, enable_gateway


def _settings(tmp_path, **updates):
    values = {
        "_env_file": None,
        "model_provider": "mock",
        "database_path": tmp_path / "agent.db",
        "audit_dir": tmp_path / "audit",
        "authorized_file_roots": [tmp_path / "files"],
        "knowledge_roots": [tmp_path / "knowledge"],
        "meeting_output_dir": tmp_path / "meeting",
        "ruoyi_jwt_secret": TEST_JWT_SECRET_B64,
    }
    values.update(updates)
    return Settings(**values)


@pytest.mark.asyncio
async def test_developer_role_gates_internal_routes_and_ignores_role_header(tmp_path):
    app = create_app(_settings(tmp_path))
    async with app.router.lifespan_context(app):
        gateway = enable_gateway(app)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", headers=gateway.headers()
        ) as client:
            assert (await client.get("/auth/me")).json()["role"] == "user"
            created = await client.post("/tasks", json={"text": "1+1等于多少？"})
            assert created.status_code == 201
            task_id = created.json()["id"]
            # Caller-supplied role headers never authorize anything.
            forged = await client.get("/meta/capabilities", headers={"X-Agent-Role": "developer"})
            assert forged.status_code == 403
            assert (await client.get("/meta/capabilities")).status_code == 403
            assert (await client.get("/openapi.json")).status_code == 403
            assert (await client.get("/admin/settings")).status_code == 403
            # The retired password endpoints are gone for good (the fallthrough
            # static mount answers non-GET with 405, never 200).
            assert (await client.post("/auth/developer/login", json={"password": "x"})).status_code in {404, 405}
            assert (await client.post("/auth/logout")).status_code in {404, 405}
            # A developer-role token opens the same surfaces.
            gateway.promote(client)
            assert (await client.get("/auth/me")).json()["role"] == "developer"
            assert (await client.get("/meta/capabilities")).status_code == 200
            assert (await client.get("/openapi.json")).status_code == 200
            assert (await client.get("/admin/settings")).status_code == 200
            # Developer identity is a different account: its data space is separate.
            assert (await client.get(f"/tasks/{task_id}")).status_code == 403


def test_non_loopback_binding_no_longer_requires_a_password(tmp_path):
    # The old DEVELOPER_PASSWORD requirement for non-loopback hosts retired
    # with the password gate; the RuoYi token gate now covers every data
    # endpoint regardless of the bind address.
    assert _settings(tmp_path, host="0.0.0.0").host == "0.0.0.0"
    assert _settings(tmp_path, host="127.0.0.1").host == "127.0.0.1"


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
            f"secret={TEST_JWT_SECRET_B64} request_text=private task C:\\Users\\name\\data.txt"
        )
        gateway = enable_gateway(app)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", headers=gateway.headers(username="dev1", user_id=101, role_keys=("developer",))
        ) as client:
            payload = (await client.get("/developer/logs")).json()
            assert payload["count"] <= payload["limit"] == 200
            text = str(payload)
            assert TEST_JWT_SECRET_B64 not in text
            assert "private task" not in text
            assert "C:\\Users\\name" not in text
