"""Redacted append-only daily JSONL audit storage."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from agent_platform.core.data_classification import DataClassificationService
from agent_platform.models import AuditEvent


class AuditService:
    def __init__(
        self,
        directory: Path,
        classifier: DataClassificationService,
        *,
        retention_days: int = 30,
        flush_size: int = 10,
    ) -> None:
        self._directory = directory.resolve()
        self._directory.mkdir(parents=True, exist_ok=True)
        self._classifier = classifier
        self._retention_days = retention_days
        self._flush_size = flush_size
        self._buffer: list[AuditEvent] = []
        self._lock = asyncio.Lock()

    async def record(self, event: AuditEvent) -> None:
        safe_event = event.model_copy(
            update={
                "input_summary": self._classifier.classify(event.input_summary).redacted_text,
                "output_summary": self._classifier.classify(event.output_summary).redacted_text,
                "decision": self._classifier.classify(event.decision).redacted_text,
            }
        )
        async with self._lock:
            self._buffer.append(safe_event)
            if len(self._buffer) >= self._flush_size:
                self._flush_unlocked()

    async def flush(self) -> None:
        async with self._lock:
            self._flush_unlocked()

    def _flush_unlocked(self) -> None:
        if not self._buffer:
            return
        grouped: dict[str, list[AuditEvent]] = {}
        for event in self._buffer:
            key = event.timestamp.strftime("%Y-%m-%d")
            grouped.setdefault(key, []).append(event)
        for day, events in grouped.items():
            path = self._directory / f"audit-{day}.jsonl"
            with path.open("a", encoding="utf-8", newline="\n") as handle:
                for event in events:
                    handle.write(event.model_dump_json() + "\n")
        self._buffer.clear()

    async def by_task(self, task_id: UUID) -> list[AuditEvent]:
        await self.flush()
        result: list[AuditEvent] = []
        for path in sorted(self._directory.glob("audit-*.jsonl")):
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    event = AuditEvent.model_validate_json(line)
                    if event.task_id == task_id:
                        result.append(event)
        return result

    async def purge_expired(self, *, now: datetime | None = None) -> int:
        cutoff = ((now or datetime.now(UTC)) - timedelta(days=self._retention_days)).date()
        removed = 0
        async with self._lock:
            self._flush_unlocked()
            for path in self._directory.glob("audit-*.jsonl"):
                try:
                    day = datetime.strptime(path.stem.removeprefix("audit-"), "%Y-%m-%d")
                except ValueError:
                    continue
                if day.date() < cutoff:
                    path.unlink()
                    removed += 1
        return removed


__all__ = ["AuditService"]
