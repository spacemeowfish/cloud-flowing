"""Bounded, sanitized log records for the developer console."""

from __future__ import annotations

import logging
import re
from collections import deque
from datetime import UTC, datetime
from threading import Lock


_SECRET = re.compile(
    r"(?i)\b(password|passwd|token|cookie|authorization|api[_-]?key|secret)\b\s*[:=]\s*([^\s,;]+)"
)
_WINDOWS_PATH = re.compile(r"(?i)(?<![\w])(?:[a-z]:\\|\\\\)[^\s,;]+")
_UNIX_PATH = re.compile(
    r"(?<![\w.])/(?:home|Users|var|tmp|opt|etc|usr|mnt|data|root)/(?:[^\s/,]+/)*[^\s,;]*"
)
_TASK_TEXT = re.compile(r"(?i)\b(request_text|task_text|prompt|input)\b\s*[:=]\s*([^\r\n]+)")


def sanitize_log_message(message: str, secrets: tuple[str, ...] = ()) -> str:
    sanitized = message.replace("\r", " ").replace("\n", " ")
    for secret in secrets:
        if secret:
            sanitized = sanitized.replace(secret, "[REDACTED]")
    sanitized = _TASK_TEXT.sub(lambda match: f"{match.group(1)}=[REDACTED]", sanitized)
    sanitized = _SECRET.sub(lambda match: f"{match.group(1)}=[REDACTED]", sanitized)
    sanitized = _WINDOWS_PATH.sub("[LOCAL_PATH]", sanitized)
    sanitized = _UNIX_PATH.sub("[LOCAL_PATH]", sanitized)
    return sanitized[:1000]


class RecentLogHandler(logging.Handler):
    """Capture a small process-local window without retaining request bodies."""

    def __init__(self, *, capacity: int = 200, secrets: tuple[str, ...] = ()) -> None:
        super().__init__()
        self._records: deque[dict[str, str]] = deque(maxlen=capacity)
        self._secrets = secrets
        self._lock = Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            item = {
                "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
                "level": record.levelname,
                "module": record.name,
                "message": sanitize_log_message(record.getMessage(), self._secrets),
            }
            with self._lock:
                self._records.append(item)
        except Exception:
            self.handleError(record)

    def recent(self) -> list[dict[str, str]]:
        with self._lock:
            return list(self._records)


__all__ = ["RecentLogHandler", "sanitize_log_message"]
