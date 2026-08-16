"""Small in-memory developer session service."""

from __future__ import annotations

import hmac
import secrets
from threading import Lock


class DeveloperSessionService:
    """Validate one local password and keep process-lifetime login tokens."""

    def __init__(self, password: str) -> None:
        self._password = password
        self._tokens: set[str] = set()
        self._lock = Lock()

    @property
    def configured(self) -> bool:
        return bool(self._password)

    def login(self, candidate: str) -> str | None:
        expected = self._password.encode("utf-8")
        supplied = candidate.encode("utf-8")
        if not self.configured or not hmac.compare_digest(supplied, expected):
            return None
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._tokens.add(token)
        return token

    def is_valid(self, token: str | None) -> bool:
        if not token:
            return False
        with self._lock:
            return token in self._tokens

    def logout(self, token: str | None) -> None:
        if not token:
            return
        with self._lock:
            self._tokens.discard(token)


__all__ = ["DeveloperSessionService"]
