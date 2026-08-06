"""Task and session protocol models."""

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field, JsonValue

from agent_platform.models.common import DataLevel, RiskLevel, StrictModel


class TaskState(StrEnum):
    RECEIVED = "received"
    UNDERSTANDING = "understanding"
    VALIDATING = "validating"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    EXECUTING = "executing"
    DELIVERING = "delivering"
    WAITING_NETWORK = "waiting_network"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskEvent(StrEnum):
    UNDERSTAND = "understand"
    VALIDATE = "validate"
    REQUIRE_CONFIRMATION = "require_confirmation"
    CONFIRM = "confirm"
    EXECUTE = "execute"
    DELIVER = "deliver"
    COMPLETE = "complete"
    WAIT_NETWORK = "wait_network"
    RESUME = "resume"
    FAIL = "fail"
    CANCEL = "cancel"


class TaskCreate(StrictModel):
    text: str = Field(..., min_length=1, max_length=20_000, description="Natural-language request")
    session_id: str = Field(default="default", min_length=1, description="Caller session identifier")
    role: str = Field(default="user", min_length=1, description="Authenticated role from upstream")
    data_domain: str = Field(default="personal", min_length=1, description="Authorized data domain")


class TaskRecord(StrictModel):
    id: UUID = Field(default_factory=uuid4, description="Stable task identifier")
    session_id: str = Field(default="default", description="Owning session")
    request_text: str = Field(..., description="Original request")
    state: TaskState = Field(default=TaskState.RECEIVED, description="Current lifecycle state")
    context: dict[str, JsonValue] = Field(default_factory=dict, description="Serializable task context")
    result: dict[str, JsonValue] | None = Field(default=None, description="Final or intermediate result")
    error: str | None = Field(default=None, description="Sanitized terminal error")
    risk_level: RiskLevel = Field(default=RiskLevel.R0, description="Effective operation risk")
    data_level: DataLevel = Field(default=DataLevel.D0, description="Highest detected data class")
    version: int = Field(default=0, ge=0, description="Optimistic lock version")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), description="Creation time in UTC")
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC), description="Last update time in UTC")


class TaskConfirmation(StrictModel):
    arguments: dict[str, JsonValue] = Field(default_factory=dict, description="Confirmed or corrected arguments")
    approved: bool = Field(default=True, description="Whether execution is approved")


class TaskCancel(StrictModel):
    reason: str = Field(default="user_cancelled", max_length=500, description="Cancellation reason")


TERMINAL_STATES = frozenset({TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED})

__all__ = [
    "TERMINAL_STATES",
    "TaskCancel",
    "TaskConfirmation",
    "TaskCreate",
    "TaskEvent",
    "TaskRecord",
    "TaskState",
]
