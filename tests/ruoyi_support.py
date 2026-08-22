"""Shared RuoYi gateway test helpers: mock issuer, fake session store, clients.

Mirrors the mock-issuer strategy frozen in the contract appendix B: tokens are
real HS512 JWTs signed with the same base64-decoded-key semantics as RuoYi,
and session values replicate the FastJson2 notation from contract appendix A
(``@type`` markers, ``Set[...]``, trailing-``L`` longs) so the tolerant parser
is exercised against realistic bytes.
"""

from __future__ import annotations

import base64
import uuid
from typing import Any

import httpx
import jwt

from agent_platform.core.ruoyi_auth import (
    LOGIN_TOKEN_PREFIX,
    RuoYiAuthenticator,
    RuoYiTokenVerifier,
)

# 96 decoded bytes: satisfies the >=64-byte HS512 floor the settings enforce.
TEST_JWT_SECRET_B64 = base64.b64encode(b"ruoyi-gateway-test-secret" * 4).decode("ascii")

# Byte-exact login_tokens Redis value captured from the local RuoYi instance
# (contract appendix A.2), trimmed to the identity-relevant fields and
# regenerated per call for the requested account.
def session_value(
    user_id: int = 100,
    username: str = "user1",
    role_keys: tuple[str, ...] = ("common",),
    is_admin: bool | None = None,
    token_key: str = "test-key",
) -> str:
    admin = (user_id == 1) if is_admin is None else is_admin
    roles = ",".join(
        '{"admin":false,"dataScope":"2","deptCheckStrictly":false,"flag":false,'
        '"menuCheckStrictly":false,"params":{"@type":"java.util.HashMap"},'
        f'"permissions":Set[],"roleId":{index + 1}L,"roleKey":"{key}",'
        f'"roleName":"role{index}","roleSort":{index + 1},"status":"0"}}'
        for index, key in enumerate(role_keys)
    )
    return (
        '{"@type":"com.ruoyi.common.core.domain.model.LoginUser","browser":"pytest",'
        '"deptId":103L,"expireTime":9999999999999,"ipaddr":"127.0.0.1",'
        '"loginLocation":"内网IP","loginTime":1,"os":"pytest","permissions":Set[],'
        f'"token":"{token_key}",'
        '"user":{"admin":' + ("true" if admin else "false") + "," + f'"createBy":"admin",'
        '"dept":{"ancestors":"0,100,101","children":[],"deptId":103L,"deptName":"研发部门",'
        '"leader":"若依","orderNum":1,"params":{"@type":"java.util.HashMap"},"parentId":101L,"status":"0"},'
        '"deptId":103L,"params":{"@type":"java.util.HashMap"},"roles":[' + roles + "],"
        f'"sex":"0","status":"0","userId":{user_id}L,"userName":"{username}"}},'
        f'"userId":{user_id}L,"username":"{username}"}}'
    )


class FakeRuoYiSessionStore:
    """In-memory ``login_tokens:{uuid}`` map with optional outage injection."""

    def __init__(self) -> None:
        self.sessions: dict[str, str] = {}
        self.outage = False

    async def get(self, token_key: str) -> str | None:
        if self.outage:
            raise ConnectionError("fake redis outage")
        return self.sessions.get(token_key)

    async def close(self) -> None:
        return None

    def register(self, token_key: str, value: str) -> None:
        self.sessions[token_key] = value

    def revoke(self, token_key: str) -> None:
        self.sessions.pop(token_key, None)


class TestGateway:
    """Swap the app's authenticator for the mock issuer + fake store."""

    def __init__(self, app: Any) -> None:
        self.app = app
        self.store = FakeRuoYiSessionStore()
        self.authenticator = RuoYiAuthenticator(
            RuoYiTokenVerifier(TEST_JWT_SECRET_B64), self.store
        )
        app.state.ruoyi_authenticator = self.authenticator

    def issue(
        self,
        *,
        username: str = "user1",
        user_id: int = 100,
        role_keys: tuple[str, ...] = ("common",),
        is_admin: bool | None = None,
    ) -> str:
        token_key = uuid.uuid4().hex
        token = jwt.encode(
            {"sub": username, "login_user_key": token_key},
            base64.b64decode(TEST_JWT_SECRET_B64),
            algorithm="HS512",
        )
        self.store.register(
            token_key,
            session_value(
                user_id=user_id,
                username=username,
                role_keys=role_keys,
                is_admin=is_admin,
                token_key=token_key,
            ),
        )
        return token

    def headers(self, **kwargs: Any) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.issue(**kwargs)}"}

    def promote(
        self,
        client: httpx.AsyncClient,
        *,
        username: str = "dev1",
        user_id: int = 101,
        role_keys: tuple[str, ...] = ("developer",),
        is_admin: bool | None = None,
    ) -> None:
        """Switch an existing client to a developer-capable identity."""

        client.headers["Authorization"] = f"Bearer {self.issue(username=username, user_id=user_id, role_keys=role_keys, is_admin=is_admin)}"

    def demote(self, client: httpx.AsyncClient) -> None:
        """Switch a client back to a plain user identity (post-"logout")."""

        client.headers["Authorization"] = f"Bearer {self.issue()}"

    def revoke(self, token: str) -> None:
        payload = jwt.decode(token, base64.b64decode(TEST_JWT_SECRET_B64), algorithms=["HS512"])
        self.store.revoke(str(payload["login_user_key"]))


def enable_gateway(app: Any) -> TestGateway:
    return TestGateway(app)


__all__ = [
    "LOGIN_TOKEN_PREFIX",
    "TEST_JWT_SECRET_B64",
    "FakeRuoYiSessionStore",
    "TestGateway",
    "enable_gateway",
    "session_value",
]
