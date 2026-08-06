"""Persistent FIFO offline queue sharing SessionManager storage."""

import json
from uuid import UUID

from pydantic import JsonValue

from agent_platform.core.data_classification import DataClassificationService
from agent_platform.core.errors import SensitiveDataError
from agent_platform.core.session_manager import SessionManager


class OfflineTaskQueue:
    def __init__(self, store: SessionManager, classifier: DataClassificationService) -> None:
        self._store = store
        self._classifier = classifier

    async def enqueue(self, task_id: UUID, payload: dict[str, JsonValue], idempotency_key: str) -> None:
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        result = self._classifier.classify(serialized)
        if result.level.value == "D3":
            raise SensitiveDataError("D3 data cannot be saved to the offline queue")
        await self._store.execute(
            "INSERT OR IGNORE INTO offline_queue(task_id, payload, idempotency_key, cancelled) VALUES (?, ?, ?, 0)",
            (str(task_id), result.redacted_text, idempotency_key),
        )

    async def cancel(self, task_id: UUID) -> None:
        await self._store.execute("UPDATE offline_queue SET cancelled = 1 WHERE task_id = ?", (str(task_id),))

    async def pending(self) -> list[dict[str, object]]:
        rows = await self._store.query(
            "SELECT sequence, task_id, payload, idempotency_key FROM offline_queue WHERE cancelled = 0 ORDER BY sequence"
        )
        for row in rows:
            row["payload"] = json.loads(str(row["payload"]))
        return rows

    async def mark_complete(self, task_id: UUID) -> None:
        await self._store.execute("DELETE FROM offline_queue WHERE task_id = ?", (str(task_id),))

    async def depth(self) -> int:
        rows = await self._store.query("SELECT COUNT(*) AS count FROM offline_queue WHERE cancelled = 0")
        return int(rows[0]["count"])


__all__ = ["OfflineTaskQueue"]

