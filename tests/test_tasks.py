import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from agent_platform.core.errors import ConcurrencyConflictError, DatabaseInUseError, InvalidTransitionError
from agent_platform.core.session_manager import SessionManager
from agent_platform.core.task_api import TaskAPI
from agent_platform.core.task_state_machine import TaskStateMachine
from agent_platform.models import TaskCreate, TaskEvent, TaskRecord, TaskState


LEGAL_PATH = [
    (TaskState.RECEIVED, TaskEvent.UNDERSTAND, TaskState.UNDERSTANDING),
    (TaskState.UNDERSTANDING, TaskEvent.VALIDATE, TaskState.VALIDATING),
    (TaskState.VALIDATING, TaskEvent.REQUIRE_CONFIRMATION, TaskState.AWAITING_CONFIRMATION),
    (TaskState.AWAITING_CONFIRMATION, TaskEvent.CONFIRM, TaskState.VALIDATING),
    (TaskState.VALIDATING, TaskEvent.EXECUTE, TaskState.EXECUTING),
    (TaskState.EXECUTING, TaskEvent.DELIVER, TaskState.DELIVERING),
    (TaskState.DELIVERING, TaskEvent.COMPLETE, TaskState.COMPLETED),
]


@pytest.mark.parametrize("state,event,expected", LEGAL_PATH)
def test_legal_transitions(state, event, expected):
    assert TaskStateMachine.transition(state, event) == expected


@pytest.mark.parametrize(
    "state,event",
    [
        (TaskState.RECEIVED, TaskEvent.COMPLETE),
        (TaskState.RECEIVED, TaskEvent.EXECUTE),
        (TaskState.UNDERSTANDING, TaskEvent.COMPLETE),
        (TaskState.VALIDATING, TaskEvent.COMPLETE),
        (TaskState.AWAITING_CONFIRMATION, TaskEvent.EXECUTE),
        (TaskState.EXECUTING, TaskEvent.COMPLETE),
        (TaskState.DELIVERING, TaskEvent.EXECUTE),
        (TaskState.COMPLETED, TaskEvent.CANCEL),
        (TaskState.FAILED, TaskEvent.UNDERSTAND),
        (TaskState.CANCELLED, TaskEvent.RESUME),
    ],
)
def test_illegal_transitions(state, event):
    with pytest.raises(InvalidTransitionError):
        TaskStateMachine.transition(state, event)


@pytest.mark.asyncio
async def test_persistence_recovery_and_cancellation(tmp_path):
    path = tmp_path / "tasks.db"
    store = SessionManager(path)
    tasks = TaskAPI(store)
    task = await tasks.create(TaskCreate(text="hello"))
    task = await tasks.transition(task.id, TaskEvent.UNDERSTAND)
    await store.close()

    recovered_store = SessionManager(path)
    recovered_api = TaskAPI(recovered_store)
    recovered = await recovered_api.initialize()
    assert recovered[0].id == task.id
    assert recovered[0].state == TaskState.UNDERSTANDING
    cancelled = await recovered_api.cancel(task.id)
    assert cancelled.state == TaskState.CANCELLED
    assert recovered_api.cancellation_event(task.id).is_set()
    await recovered_store.close()


def test_second_manager_rejected(tmp_path):
    first = SessionManager(tmp_path / "tasks.db")
    with pytest.raises(DatabaseInUseError):
        SessionManager(tmp_path / "tasks.db")
    asyncio.run(first.close())


@pytest.mark.asyncio
async def test_optimistic_lock_conflict(tmp_path):
    store = SessionManager(tmp_path / "tasks.db")
    task = await store.create(TaskRecord(request_text="x"))
    first = task.model_copy(update={"state": TaskState.UNDERSTANDING})
    await store.update(first, 0)
    with pytest.raises(ConcurrencyConflictError):
        await store.update(first, 0)
    await store.close()


@pytest.mark.asyncio
async def test_terminal_retention_and_sse_subscription(tmp_path):
    store = SessionManager(tmp_path / "tasks.db")
    tasks = TaskAPI(store)
    old = TaskRecord(
        request_text="old",
        state=TaskState.COMPLETED,
        updated_at=datetime.now(UTC) - timedelta(days=31),
    )
    active = TaskRecord(
        request_text="active",
        state=TaskState.UNDERSTANDING,
        updated_at=datetime.now(UTC) - timedelta(days=31),
    )
    await store.create(old)
    await store.create(active)
    assert await store.purge_expired(30) == 1
    assert (await store.get(str(active.id))).state == TaskState.UNDERSTANDING

    fresh = await tasks.create(TaskCreate(text="subscribe"))
    queue = await tasks.subscribe(fresh.id)
    await tasks.transition(fresh.id, TaskEvent.UNDERSTAND)
    update = await asyncio.wait_for(queue.get(), timeout=0.5)
    assert update.state == TaskState.UNDERSTANDING
    tasks.unsubscribe(fresh.id, queue)
    await store.close()
