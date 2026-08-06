"""Task creation, transition, cancellation, and state subscriptions."""

import asyncio
from datetime import UTC, datetime
from uuid import UUID

from pydantic import JsonValue

from agent_platform.core.errors import ConcurrencyConflictError
from agent_platform.core.session_manager import SessionManager
from agent_platform.core.task_state_machine import TaskStateMachine
from agent_platform.models import DataLevel, RiskLevel, TaskCreate, TaskEvent, TaskRecord


class TaskAPI:
    """Own in-memory cancellation events while persisting every state change."""

    def __init__(self, store: SessionManager) -> None:
        self._store = store
        self._cancel_events: dict[UUID, asyncio.Event] = {}
        self._subscribers: dict[UUID, set[asyncio.Queue[TaskRecord]]] = {}

    async def initialize(self) -> list[TaskRecord]:
        recovered = await self._store.recover_incomplete()
        for task in recovered:
            self._cancel_events[task.id] = asyncio.Event()
        return recovered

    async def create(self, request: TaskCreate) -> TaskRecord:
        task = TaskRecord(session_id=request.session_id, request_text=request.text)
        await self._store.create(task)
        self._cancel_events[task.id] = asyncio.Event()
        await self._publish(task)
        return task

    async def get(self, task_id: UUID | str) -> TaskRecord:
        return await self._store.get(str(task_id))

    async def list(self, session_id: str, limit: int = 50) -> list[TaskRecord]:
        return await self._store.list_tasks(session_id, limit)

    async def transition(
        self,
        task_id: UUID | str,
        event: TaskEvent,
        *,
        context_update: dict[str, JsonValue] | None = None,
        result: dict[str, JsonValue] | None = None,
        error: str | None = None,
        risk_level: RiskLevel | None = None,
        data_level: DataLevel | None = None,
    ) -> TaskRecord:
        for attempt in range(2):
            task = await self._store.get(str(task_id))
            new_state = TaskStateMachine.transition(task.state, event)
            context = dict(task.context)
            if context_update:
                context.update(context_update)
            candidate = task.model_copy(
                update={
                    "state": new_state,
                    "context": context,
                    "result": result if result is not None else task.result,
                    "error": error,
                    "risk_level": risk_level if risk_level is not None else task.risk_level,
                    "data_level": data_level if data_level is not None else task.data_level,
                    "updated_at": datetime.now(UTC),
                }
            )
            try:
                updated = await self._store.update(candidate, task.version)
                await self._publish(updated)
                return updated
            except ConcurrencyConflictError:
                if attempt == 1:
                    raise
        raise AssertionError("unreachable")

    async def cancel(self, task_id: UUID | str, reason: str = "user_cancelled") -> TaskRecord:
        task = await self._store.get(str(task_id))
        event = self._cancel_events.setdefault(task.id, asyncio.Event())
        event.set()
        return await self.transition(task.id, TaskEvent.CANCEL, error=reason)

    def cancellation_event(self, task_id: UUID) -> asyncio.Event:
        return self._cancel_events.setdefault(task_id, asyncio.Event())

    async def subscribe(self, task_id: UUID) -> asyncio.Queue[TaskRecord]:
        queue: asyncio.Queue[TaskRecord] = asyncio.Queue(maxsize=20)
        self._subscribers.setdefault(task_id, set()).add(queue)
        return queue

    def unsubscribe(self, task_id: UUID, queue: asyncio.Queue[TaskRecord]) -> None:
        subscribers = self._subscribers.get(task_id)
        if subscribers:
            subscribers.discard(queue)
            if not subscribers:
                self._subscribers.pop(task_id, None)

    async def _publish(self, task: TaskRecord) -> None:
        for queue in tuple(self._subscribers.get(task.id, ())):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(task)


__all__ = ["TaskAPI"]
