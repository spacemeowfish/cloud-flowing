"""Explicit task lifecycle with no string-based transitions."""

from agent_platform.core.errors import InvalidTransitionError
from agent_platform.models import TaskEvent, TaskState


class TaskStateMachine:
    """Validate every state change against the seven-step task lifecycle."""

    TRANSITIONS: dict[tuple[TaskState, TaskEvent], TaskState] = {
        (TaskState.RECEIVED, TaskEvent.UNDERSTAND): TaskState.UNDERSTANDING,
        (TaskState.UNDERSTANDING, TaskEvent.VALIDATE): TaskState.VALIDATING,
        (TaskState.VALIDATING, TaskEvent.REQUIRE_CONFIRMATION): TaskState.AWAITING_CONFIRMATION,
        (TaskState.VALIDATING, TaskEvent.EXECUTE): TaskState.EXECUTING,
        (TaskState.VALIDATING, TaskEvent.WAIT_NETWORK): TaskState.WAITING_NETWORK,
        (TaskState.AWAITING_CONFIRMATION, TaskEvent.CONFIRM): TaskState.VALIDATING,
        (TaskState.EXECUTING, TaskEvent.REQUIRE_CONFIRMATION): TaskState.AWAITING_CONFIRMATION,
        (TaskState.EXECUTING, TaskEvent.DELIVER): TaskState.DELIVERING,
        (TaskState.EXECUTING, TaskEvent.WAIT_NETWORK): TaskState.WAITING_NETWORK,
        (TaskState.DELIVERING, TaskEvent.COMPLETE): TaskState.COMPLETED,
        (TaskState.WAITING_NETWORK, TaskEvent.RESUME): TaskState.VALIDATING,
    }

    for _state in TaskState:
        if _state not in {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}:
            TRANSITIONS[(_state, TaskEvent.CANCEL)] = TaskState.CANCELLED
            TRANSITIONS[(_state, TaskEvent.FAIL)] = TaskState.FAILED

    @classmethod
    def transition(cls, current: TaskState, event: TaskEvent) -> TaskState:
        try:
            return cls.TRANSITIONS[(current, event)]
        except KeyError as exc:
            raise InvalidTransitionError(f"Cannot apply {event.value} while task is {current.value}") from exc


__all__ = ["TaskStateMachine"]

