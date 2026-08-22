"""RuoYi JWT gateway authentication.

Implements ``docs/contracts/ruoyi-auth-gateway.md`` (2026-08-20 定稿):

- HS512 verification with the base64-decoded shared secret (jjwt 0.9.1
  semantics; the raw secret bytes never verify).
- The JWT carries only ``sub`` + ``login_user_key`` and no ``exp``; validity
  lives entirely in the RuoYi Redis key ``login_tokens:{uuid}`` TTL, so every
  request must confirm the key still exists. This store is read-only: the
  gateway never writes and never renews sessions.
- The Redis value is FastJson2 output (``@type`` markers, ``Set[...]``,
  trailing-``L`` longs), not standard JSON; extraction uses a tolerant parser
  and any parse failure fails closed.
- Identity: data ownership is keyed by immutable ``userId``; the developer
  role is derived from ``user.admin`` (equivalently ``userId == 1``) or
  roleKey membership in {admin, developer}. Caller-supplied role headers are
  never trusted.
"""

from __future__ import annotations

import base64
import binascii
import logging
import re
from dataclasses import dataclass
from typing import Protocol

import jwt

LOGIN_TOKEN_PREFIX = "login_tokens:"
DEVELOPER_ROLE_KEYS = frozenset({"admin", "developer"})
_BEARER_PREFIX = "Bearer "

logger = logging.getLogger("agent_platform.ruoyi_auth")


@dataclass(frozen=True)
class RuoYiTokenClaims:
    """Verified JWT payload (contract §2: exactly ``sub`` + ``login_user_key``)."""

    username: str
    login_user_key: str


@dataclass(frozen=True)
class RuoYiSessionIdentity:
    """Identity fields extracted from the Redis session value (contract §4)."""

    user_id: int
    username: str | None
    is_admin: bool
    role_keys: tuple[str, ...]


@dataclass(frozen=True)
class AuthenticatedIdentity:
    """Request identity after both verification steps (contract §6)."""

    user_id: int
    username: str
    role: str
    session_id: str


class RuoYiTokenVerifier:
    """Verify RuoYi-issued JWTs with the shared base64-encoded HS512 secret."""

    def __init__(self, secret_b64: str) -> None:
        self._key = b""
        stripped = secret_b64.strip()
        if stripped:
            try:
                self._key = base64.b64decode(stripped, validate=True)
            except (ValueError, binascii.Error):
                logger.error("RUOYI_JWT_SECRET is not valid base64; every token will be rejected")

    @property
    def configured(self) -> bool:
        return bool(self._key)

    def verify(self, token: str) -> RuoYiTokenClaims | None:
        if not self._key or not token:
            return None
        try:
            payload = jwt.decode(token, self._key, algorithms=["HS512"])
        except jwt.PyJWTError:
            return None
        username = payload.get("sub")
        login_user_key = payload.get("login_user_key")
        if not isinstance(username, str) or not username:
            return None
        if not isinstance(login_user_key, str) or not login_user_key:
            return None
        return RuoYiTokenClaims(username=username, login_user_key=login_user_key)


class RuoYiSessionStore(Protocol):
    """Read-only access to RuoYi login sessions in Redis."""

    async def get(self, token_key: str) -> str | None:
        """Return the raw value stored under ``login_tokens:{token_key}`` or None."""
        ...


class RedisRuoYiSessionStore:
    """Adapter over redis.asyncio; existence of the key is the validity check."""

    def __init__(self, client: object) -> None:
        self._client = client

    async def get(self, token_key: str) -> str | None:
        value = await self._client.get(LOGIN_TOKEN_PREFIX + token_key)  # type: ignore[attr-defined]
        if value is None:
            return None
        return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)

    async def close(self) -> None:
        close = getattr(self._client, "aclose", None) or getattr(self._client, "close", None)
        if close is not None:
            result = close()
            if hasattr(result, "__await__"):
                await result


def parse_login_user(raw: str) -> RuoYiSessionIdentity | None:
    """Tolerantly extract identity fields from a FastJson2 LoginUser value.

    Field order and notation vary with fastjson2 versions; extraction follows
    the contract's frozen priority and never trusts structure beyond the
    documented fields. ``userId`` is mandatory — a value without a usable
    userId cannot own data and fails closed.
    """

    if not raw:
        return None

    # Top-level userId is the getter-serialized property whose key is followed
    # by "username" (lowercase n); inside the user object the neighbour is
    # "userName". Fall back to any userId occurrence (= user.userId).
    match = re.search(r'"userId":(\d+)L?,"username"', raw)
    if match is None:
        fallback = re.findall(r'"userId":(\d+)L?', raw)
        if not fallback:
            return None
        user_id = int(fallback[0])
    else:
        user_id = int(match.group(1))

    # Top-level username (lowercase key boundary excludes "userName").
    username_match = re.search(r'"username":"([^"]+)"', raw)
    if username_match is None:
        username_match = re.search(r'"userName":"([^"]+)"', raw)
    username = username_match.group(1) if username_match else None

    # user.admin is serialized from SysUser.isAdmin() and is the first
    # "admin" field in the value (the user object precedes its roles).
    admin_match = re.search(r'"admin":(true|false)', raw)
    if admin_match is not None:
        is_admin = admin_match.group(1) == "true"
    else:
        is_admin = user_id == 1

    role_keys = tuple(re.findall(r'"roleKey":"([^"]*)"', raw))
    return RuoYiSessionIdentity(
        user_id=user_id,
        username=username,
        is_admin=is_admin,
        role_keys=role_keys,
    )


class RuoYiAuthenticator:
    """Two-step gate: verify the JWT signature, then confirm the live session."""

    def __init__(self, verifier: RuoYiTokenVerifier, store: RuoYiSessionStore) -> None:
        self._verifier = verifier
        self._store = store

    @property
    def store(self) -> RuoYiSessionStore:
        """Exposed so tests can swap in a fake session store."""

        return self._store

    async def close(self) -> None:
        close = getattr(self._store, "close", None)
        if close is not None:
            result = close()
            if hasattr(result, "__await__"):
                await result

    async def authenticate(self, authorization_header: str | None) -> AuthenticatedIdentity | None:
        if not authorization_header or not authorization_header.startswith(_BEARER_PREFIX):
            return None
        token = authorization_header[len(_BEARER_PREFIX):].strip()
        if not token:
            return None
        claims = self._verifier.verify(token)
        if claims is None:
            return None
        raw = await self._store.get(claims.login_user_key)
        if not raw:
            # Revoked (key deleted) or expired (TTL elapsed) — same verdict.
            return None
        session = parse_login_user(raw)
        if session is None:
            return None
        is_developer = session.is_admin or any(key in DEVELOPER_ROLE_KEYS for key in session.role_keys)
        username = session.username or claims.username
        return AuthenticatedIdentity(
            user_id=session.user_id,
            username=username,
            role="developer" if is_developer else "user",
            session_id=f"user:{session.user_id}",
        )


__all__ = [
    "AuthenticatedIdentity",
    "DEVELOPER_ROLE_KEYS",
    "LOGIN_TOKEN_PREFIX",
    "RedisRuoYiSessionStore",
    "RuoYiAuthenticator",
    "RuoYiSessionIdentity",
    "RuoYiSessionStore",
    "RuoYiTokenClaims",
    "RuoYiTokenVerifier",
    "parse_login_user",
]
