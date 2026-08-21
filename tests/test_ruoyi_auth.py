"""RuoYi gateway authentication: verifier, tolerant parser, gate, isolation.

Contract reference: ``docs/contracts/ruoyi-auth-gateway.md`` (2026-08-20 定稿),
appendix B test matrix. The REAL_* fixtures are byte-exact captures from the
local RuoYi instance (contract appendix A); the parser must keep working
against real FastJson2 notation, not only synthetic values.
"""

from __future__ import annotations

import base64
import json

import httpx
import jwt as pyjwt
import pytest

from agent_platform.api.server import create_app
from agent_platform.config import Settings
from agent_platform.core.ruoyi_auth import (
    RuoYiAuthenticator,
    RuoYiTokenVerifier,
    parse_login_user,
)
from agent_platform.models import ToolContext

from ruoyi_support import TEST_JWT_SECRET_B64, FakeRuoYiSessionStore, enable_gateway, session_value

# --- byte-exact login_tokens value from contract appendix A.2 (user1) ---
REAL_USER1_VALUE = (
    '{"@type":"com.ruoyi.common.core.domain.model.LoginUser","browser":"Curl 8.18.0","deptId":103L,'
    '"expireTime":1787241317737,"ipaddr":"127.0.0.1","loginLocation":"内网IP","loginTime":1787239517737,'
    '"os":"","permissions":Set["system:user:list"],'
    '"token":"54c1e577-212a-48da-800c-4d65bc1e5424",'
    '"user":{"admin":false,"createBy":"admin","createTime":"2026-08-20 18:55:13","delFlag":"0",'
    '"dept":{"ancestors":"0,100,101","children":[],"deptId":103L,"deptName":"研发部门","leader":"若依",'
    '"orderNum":1,"params":{"@type":"java.util.HashMap"},"parentId":101L,"status":"0"},"deptId":103L,'
    '"loginDate":"2026-08-20 18:55:27","loginIp":"127.0.0.1","nickName":"普通用户",'
    '"params":{"@type":"java.util.HashMap"},"roles":[{"admin":false,"dataScope":"2",'
    '"deptCheckStrictly":false,"flag":false,"menuCheckStrictly":false,'
    '"params":{"@type":"java.util.HashMap"},"permissions":Set["system:user:list"],"roleId":2L,'
    '"roleKey":"common","roleName":"普通角色","roleSort":2,"status":"0"}],"sex":"0","status":"0",'
    '"userId":100L,"userName":"user1"},"userId":100L,"username":"user1"}'
)

# --- byte-exact admin identity fragments from contract appendix A.3 ---
REAL_ADMIN_USER_FRAGMENT = (
    '"user":{"admin":true,"createBy":"admin","createTime":"2026-08-20 18:41:03","delFlag":"0"'
)
REAL_ADMIN_ROLES_FRAGMENT = (
    '"roles":[{"admin":true,"dataScope":"1","deptCheckStrictly":false,"flag":false,'
    '"menuCheckStrictly":false,"params":{"@type":"java.util.HashMap"},"roleId":1L,'
    '"roleKey":"admin","roleName":"超级管理员","roleSort":1,"status":"0"}]'
)
REAL_ADMIN_TAIL_FRAGMENT = '"userId":1L,"username":"admin"}'


def _admin_value() -> str:
    """Reassemble an admin session value from the appendix A.3 byte fragments."""

    return (
        '{"@type":"com.ruoyi.common.core.domain.model.LoginUser","browser":"Curl 8.18.0",'
        '"permissions":Set["*:*:*"],'
        + REAL_ADMIN_USER_FRAGMENT
        + ',"params":{"@type":"java.util.HashMap"},'
        + REAL_ADMIN_ROLES_FRAGMENT
        + ',"sex":"1","status":"0","userId":1L,"userName":"admin"},'
        + REAL_ADMIN_TAIL_FRAGMENT
    )


def _mint(sub: str = "user1", key: str = "uuid-1", secret_b64: str = TEST_JWT_SECRET_B64) -> str:
    return pyjwt.encode(
        {"sub": sub, "login_user_key": key},
        base64.b64decode(secret_b64),
        algorithm="HS512",
    )


def _settings(tmp_path) -> Settings:
    allowed = tmp_path / "allowed"
    knowledge = tmp_path / "knowledge"
    allowed.mkdir(exist_ok=True)
    knowledge.mkdir(exist_ok=True)
    return Settings(
        model_provider="mock",
        database_path=tmp_path / "agent.db",
        audit_dir=tmp_path / "audit",
        authorized_file_roots=[allowed],
        knowledge_roots=[knowledge],
        meeting_output_dir=tmp_path / "meeting",
        audit_flush_size=1,
        ruoyi_jwt_secret=TEST_JWT_SECRET_B64,
    )


# ---------------------------------------------------------------- parser


def test_parser_extracts_identity_from_real_user1_sample():
    identity = parse_login_user(REAL_USER1_VALUE)
    assert identity is not None
    assert identity.user_id == 100
    assert identity.username == "user1"
    assert identity.is_admin is False
    assert identity.role_keys == ("common",)


def test_parser_extracts_admin_from_real_admin_fragments():
    identity = parse_login_user(_admin_value())
    assert identity is not None
    assert identity.user_id == 1
    assert identity.username == "admin"
    assert identity.is_admin is True
    assert identity.role_keys == ("admin",)


def test_parser_accepts_primitive_long_without_suffix_and_set_notation():
    value = '{"expireTime":1787241317737,"permissions":Set["a","b"],"userId":7,"username":"u7"}'
    identity = parse_login_user(value)
    assert identity is not None
    assert identity.user_id == 7
    assert identity.username == "u7"


def test_parser_falls_back_to_user_object_and_fails_closed():
    # No top-level identity: fall back to user.userId / user.userName.
    fallback = parse_login_user('{"user":{"admin":false,"userId":42L,"userName":"u42","roles":[]}}')
    assert fallback is not None
    assert fallback.user_id == 42
    assert fallback.username == "u42"
    assert fallback.role_keys == ()
    # Missing admin boolean: userId == 1 means admin.
    no_admin = parse_login_user('{"user":{"userId":1L,"userName":"root","roles":[]},"userId":1L}')
    assert no_admin is not None and no_admin.is_admin is True
    # No userId anywhere, garbage, empty: fail closed.
    assert parse_login_user('{"username":"x"}') is None
    assert parse_login_user("not json at all") is None
    assert parse_login_user("") is None


# ---------------------------------------------------------------- verifier


def test_verifier_accepts_real_semantics_and_rejects_forged():
    verifier = RuoYiTokenVerifier(TEST_JWT_SECRET_B64)
    claims = verifier.verify(_mint(sub="user1", key="uuid-1"))
    assert claims is not None
    assert claims.username == "user1"
    assert claims.login_user_key == "uuid-1"
    # Forged with different key material.
    other_secret = base64.b64encode(b"another-secret-key" * 6).decode("ascii")
    assert verifier.verify(_mint(secret_b64=other_secret)) is None
    # The Phase 1 trap: signing with the RAW secret text (no base64 decode)
    # produces a token the verifier must reject.
    raw_key = base64.b64decode(TEST_JWT_SECRET_B64)
    assert verifier.verify(
        pyjwt.encode({"sub": "user1", "login_user_key": "uuid-1"}, TEST_JWT_SECRET_B64.encode(), algorithm="HS512")
    ) is None
    # Missing claims.
    stripped = pyjwt.encode({"sub": "user1"}, raw_key, algorithm="HS512")
    assert verifier.verify(stripped) is None
    # Unconfigured verifier rejects everything.
    assert RuoYiTokenVerifier("").verify(_mint()) is None


# ---------------------------------------------------------------- settings


def test_settings_rejects_bad_secrets_and_urls(tmp_path):
    base = dict(
        model_provider="mock",
        database_path=tmp_path / "a.db",
        audit_dir=tmp_path / "audit",
    )
    with pytest.raises(ValueError):
        Settings(**base, ruoyi_jwt_secret="not base64 !!")
    with pytest.raises(ValueError):
        Settings(**base, ruoyi_jwt_secret=base64.b64encode(b"short").decode())
    with pytest.raises(ValueError):
        Settings(**base, ruoyi_redis_url="http://localhost:6379/0")
    ok = Settings(**base, ruoyi_jwt_secret=TEST_JWT_SECRET_B64)
    assert ok.ruoyi_jwt_secret == TEST_JWT_SECRET_B64


# ---------------------------------------------------------------- middleware gate


async def _client(app, headers=None):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test", headers=headers)


@pytest.mark.asyncio
async def test_gate_401_paths_and_health_whitelist(tmp_path):
    app = create_app(_settings(tmp_path))
    async with app.router.lifespan_context(app):
        gateway = enable_gateway(app)
        async with await _client(app) as client:
            # Missing token, garbage header, wrong scheme: same verdict.
            for headers in (None, {"Authorization": "garbage"}, {"Authorization": "Basic abc"}):
                response = await client.post("/tasks", json={"text": "hi"}, headers=headers)
                assert response.status_code == 401, headers
                assert response.json()["code"] == "auth_required"
                assert response.json()["retryable"] is False
            # Forged signature.
            other_secret = base64.b64encode(b"another-secret-key" * 6).decode("ascii")
            forged = {"Authorization": f"Bearer {_mint(secret_b64=other_secret)}"}
            assert (await client.post("/tasks", json={"text": "hi"}, headers=forged)).status_code == 401
            # Revoked session (Redis key deleted).
            token = gateway.issue()
            gateway.revoke(token)
            revoked = {"Authorization": f"Bearer {token}"}
            assert (await client.get("/tasks", headers=revoked)).status_code == 401
            # Auth backend outage: fail closed.
            gateway.store.outage = True
            assert (await client.get("/tasks", headers=gateway.headers())).status_code == 401
            gateway.store.outage = False
            # Session value that cannot be parsed: fail closed.
            key_only = gateway.issue()
            payload = pyjwt.decode(key_only, base64.b64decode(TEST_JWT_SECRET_B64), algorithms=["HS512"])
            gateway.store.sessions[payload["login_user_key"]] = "{{{broken"
            broken = {"Authorization": f"Bearer {key_only}"}
            assert (await client.get("/tasks", headers=broken)).status_code == 401
            # Whitelist: GET /health open; POST /health is not the whitelisted
            # method and stays behind the gate.
            health = await client.get("/health")
            assert health.status_code == 200
            assert (await client.post("/health")).status_code == 401
            # Static page shells/assets load anonymously (contract §5): the
            # console and /developer shells gate via client-side JS (Phase 4)
            # because navigations cannot carry an Authorization header;
            # developer.html is a plain asset either way.
            assert (await client.get("/")).status_code == 200
            assert (await client.get("/developer")).status_code == 200
            assert (await client.get("/app.js")).status_code == 200
            assert (await client.get("/developer.html")).status_code == 200
            # Path traversal is not an anonymous static asset.
            evil = await client.get("/../agent_platform/config/settings.py")
            assert evil.status_code == 401


@pytest.mark.asyncio
async def test_gate_role_mapping_and_identity_view(tmp_path):
    app = create_app(_settings(tmp_path))
    async with app.router.lifespan_context(app):
        gateway = enable_gateway(app)
        async with await _client(app) as client:
            # Normal user: authenticated, but developer surfaces are 403.
            client.headers["Authorization"] = f"Bearer {gateway.issue()}"
            me = await client.get("/auth/me")
            assert me.status_code == 200
            assert me.json() == {"role": "user", "username": "user1", "user_id": 100}
            assert (await client.get("/openapi.json")).status_code == 403
            assert (await client.get("/admin/settings")).status_code == 403
            # Caller-supplied role headers never grant developer.
            forged_role = {"X-Agent-Role": "developer"}
            assert (await client.get("/openapi.json", headers=forged_role)).status_code == 403
            # developer roleKey opens the console.
            client.headers["Authorization"] = f"Bearer {gateway.issue(username='dev1', user_id=101, role_keys=('developer',))}"
            assert (await client.get("/openapi.json")).status_code == 200
            me = await client.get("/auth/me")
            assert me.json()["role"] == "developer"
            # userId == 1 (super admin) opens it even without role keys.
            client.headers["Authorization"] = f"Bearer {gateway.issue(username='admin', user_id=1, role_keys=(), is_admin=True)}"
            assert (await client.get("/openapi.json")).status_code == 200


# ---------------------------------------------------------------- data isolation


@pytest.mark.asyncio
async def test_task_isolation_follows_user_id_and_cross_device_shares_data(tmp_path):
    app = create_app(_settings(tmp_path))
    async with app.router.lifespan_context(app):
        gateway = enable_gateway(app)
        async with await _client(app) as user_a, await _client(app) as user_b, await _client(app) as user_a2:
            user_a.headers["Authorization"] = f"Bearer {gateway.issue(username='a', user_id=100)}"
            user_b.headers["Authorization"] = f"Bearer {gateway.issue(username='b', user_id=200)}"
            # Fresh token, same account (another device).
            user_a2.headers["Authorization"] = f"Bearer {gateway.issue(username='a', user_id=100)}"
            created = await user_a.post("/tasks", json={"text": "查询X产品保修期"})
            assert created.status_code == 201
            task_id = created.json()["id"]
            # Another account cannot see or touch the task.
            assert (await user_b.get(f"/tasks/{task_id}")).status_code == 403
            # The same account from another device sees its data.
            same = await user_a2.get(f"/tasks/{task_id}")
            assert same.status_code == 200


@pytest.mark.asyncio
async def test_todo_store_isolation_between_owners(tmp_path):
    from agent_platform.tools.todo_tool import TodoTool

    tool = TodoTool(tmp_path / "todos.db")
    try:
        alice = ToolContext(owner="user:100")
        bob = ToolContext(owner="user:200")
        created = await tool.execute({"action": "create", "title": "alice-only"}, context=alice)
        assert created.success
        bob_view = await tool.execute({"action": "query"}, context=bob)
        assert bob_view.output["items"] == []
        alice_view = await tool.execute({"action": "query"}, context=alice)
        assert [item["title"] for item in alice_view.output["items"]] == ["alice-only"]
        # Without an owner context the tool refuses to touch any data.
        with pytest.raises(ValueError):
            await tool.execute({"action": "query"})
    finally:
        tool.close()


@pytest.mark.asyncio
async def test_executor_idempotency_cache_is_owner_scoped(tmp_path):
    from agent_platform.core.tool_executor import ToolExecutor
    from agent_platform.core.tool_registry import ToolRegistry
    from agent_platform.models import ToolCall, ToolMetadata, ToolReceipt
    from agent_platform.core.interfaces import Tool
    from pydantic import JsonValue

    class CountingTool(Tool):
        def __init__(self) -> None:
            self.calls = 0

        @property
        def metadata(self) -> ToolMetadata:
            return ToolMetadata(name="counting", description="count calls", parameters_schema={"type": "object"})

        def idempotency_key(self, arguments: dict[str, JsonValue]) -> str:
            return "mutation:counting:same-args"

        async def execute(self, arguments: dict[str, JsonValue], context=None) -> ToolReceipt:
            self.calls += 1
            return ToolReceipt(tool_name="counting", actual_arguments=arguments, success=True, output_summary="ok")

    tool = CountingTool()
    registry = ToolRegistry()
    registry.register(tool)
    registry.freeze()
    executor = ToolExecutor(registry, mutation_idempotency_ttl_seconds=60)

    alice = ToolContext(owner="user:100")
    bob = ToolContext(owner="user:200")
    call = ToolCall(task_id="00000000-0000-0000-0000-000000000000", tool_name="counting", arguments={})
    first = await executor.execute(call, context=alice)
    assert first.success
    await executor.execute(call, context=alice)  # cached for the same owner
    assert tool.calls == 1
    await executor.execute(call, context=bob)  # different owner, must re-run
    assert tool.calls == 2
    await executor.execute(call)  # no context: unnamespaced cache entry
    assert tool.calls == 3
