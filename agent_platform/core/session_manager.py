"""Single-connection SQLite task persistence with WAL and file locking."""

import asyncio
import json
import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_platform.core.errors import ConcurrencyConflictError, DatabaseInUseError, TaskNotFoundError
from agent_platform.core.interfaces import TaskStore
from agent_platform.models import TERMINAL_STATES, TaskRecord


class _DatabaseFileLock:
    def __init__(self, path: Path) -> None:
        self.path = path.with_suffix(path.suffix + ".lock")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("a+b")
        self._file.seek(0)
        if self._file.tell() == 0:
            self._file.write(b"0")
            self._file.flush()
        try:
            if os.name == "nt":
                import msvcrt

                self._file.seek(0)
                msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self._file.close()
            raise DatabaseInUseError(f"Database already in use: {path}") from exc

    def close(self) -> None:
        if self._file.closed:
            return
        try:
            if os.name == "nt":
                import msvcrt

                self._file.seek(0)
                msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
        finally:
            self._file.close()


class SessionManager(TaskStore):
    """Persist tasks immediately and recover non-terminal work after restart."""

    def __init__(self, database_path: Path) -> None:
        self.path = database_path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file_lock = _DatabaseFileLock(self.path)
        self._connection = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=NORMAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._lock = asyncio.Lock()
        self._closed = False
        self._create_schema()

    def _create_schema(self) -> None:
        # The legacy offline_queue table is intentionally not created anymore:
        # the queue had no consumer and queued tasks waited forever.  The
        # IF NOT EXISTS guard left in old databases is harmless.
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                version INTEGER NOT NULL,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_tasks_state ON tasks(state);
            """
        )

    async def create(self, task: TaskRecord) -> TaskRecord:
        payload = task.model_dump_json()
        async with self._lock:
            self._connection.execute(
                "INSERT INTO tasks(id, state, version, payload, updated_at) VALUES (?, ?, ?, ?, ?)",
                (str(task.id), task.state.value, task.version, payload, task.updated_at.isoformat()),
            )
        return task

    async def get(self, task_id: str) -> TaskRecord:
        async with self._lock:
            row = self._connection.execute("SELECT payload FROM tasks WHERE id = ?", (str(task_id),)).fetchone()
        if row is None:
            raise TaskNotFoundError(f"Task not found: {task_id}")
        return TaskRecord.model_validate_json(row["payload"])

    async def list_tasks(self, session_id: str, limit: int = 50) -> list[TaskRecord]:
        """Return the newest tasks visible to one session.

        The session identifier is intentionally read from the serialized task payload so
        existing databases do not need a schema migration.
        """

        async with self._lock:
            rows = self._connection.execute(
                "SELECT payload FROM tasks ORDER BY updated_at DESC"
            ).fetchall()
        visible: list[TaskRecord] = []
        for row in rows:
            task = TaskRecord.model_validate_json(row["payload"])
            if task.session_id == session_id:
                visible.append(task)
                if len(visible) >= limit:
                    break
        return visible

    async def update(self, task: TaskRecord, expected_version: int) -> TaskRecord:
        updated = task.model_copy(update={"version": expected_version + 1})
        payload = updated.model_dump_json()
        async with self._lock:
            cursor = self._connection.execute(
                "UPDATE tasks SET state = ?, version = ?, payload = ?, updated_at = ? WHERE id = ? AND version = ?",
                (
                    updated.state.value,
                    updated.version,
                    payload,
                    updated.updated_at.isoformat(),
                    str(updated.id),
                    expected_version,
                ),
            )
        if cursor.rowcount != 1:
            raise ConcurrencyConflictError(f"Task version conflict: {task.id}")
        return updated

    async def recover_incomplete(self) -> list[TaskRecord]:
        placeholders = ",".join("?" for _ in TERMINAL_STATES)
        states = tuple(state.value for state in TERMINAL_STATES)
        async with self._lock:
            rows = self._connection.execute(
                f"SELECT payload FROM tasks WHERE state NOT IN ({placeholders}) ORDER BY updated_at", states
            ).fetchall()
        return [TaskRecord.model_validate_json(row["payload"]) for row in rows]

    async def purge_expired(self, retention_days: int, *, now: datetime | None = None) -> int:
        """Delete only terminal tasks older than the configured retention window."""

        cutoff = (now or datetime.now(UTC)) - timedelta(days=retention_days)
        placeholders = ",".join("?" for _ in TERMINAL_STATES)
        parameters: tuple[object, ...] = (*tuple(state.value for state in TERMINAL_STATES), cutoff.isoformat())
        async with self._lock:
            cursor = self._connection.execute(
                f"DELETE FROM tasks WHERE state IN ({placeholders}) AND updated_at < ?", parameters
            )
            return cursor.rowcount

    async def execute(self, sql: str, parameters: tuple[object, ...] = ()) -> int:
        """Execute parameterized storage operations for modules sharing this connection."""

        async with self._lock:
            cursor = self._connection.execute(sql, parameters)
            return cursor.rowcount

    async def query(self, sql: str, parameters: tuple[object, ...] = ()) -> list[dict[str, object]]:
        async with self._lock:
            rows = self._connection.execute(sql, parameters).fetchall()
        return [dict(row) for row in rows]

    async def close(self) -> None:
        if self._closed:
            return
        async with self._lock:
            self._connection.close()
            self._closed = True
            self._file_lock.close()


__all__ = ["SessionManager"]
