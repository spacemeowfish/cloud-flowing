"""Structured audit protocol."""

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field

from agent_platform.models.common import DataLevel, ExecutionTarget, StrictModel


class AuditEventType(StrEnum):
    INPUT_RECEIVED = "input_received"
    MODEL_OUTPUT = "model_output"
    SCHEMA_VALIDATED = "schema_validated"
    POLICY_DECIDED = "policy_decided"
    ROUTING_DECIDED = "routing_decided"
    TOOL_CALLED = "tool_called"
    RESULT_DELIVERED = "result_delivered"
    TASK_FAILED = "task_failed"
    TASK_CANCELLED = "task_cancelled"
    CONFIRMATION_APPROVED = "confirmation_approved"
    CONFIRMATION_REJECTED = "confirmation_rejected"


class AuditEvent(StrictModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC), description="Event time in UTC")
    task_id: UUID = Field(..., description="Correlated task")
    event_type: AuditEventType = Field(..., description="Lifecycle event")
    input_summary: str = Field(default="", description="Sanitized input summary")
    output_summary: str = Field(default="", description="Sanitized output summary")
    decision: str = Field(default="", description="Decision or validation result")
    execution_target: ExecutionTarget | None = Field(default=None, description="Execution side")
    success: bool = Field(default=True, description="Whether the event step succeeded")
    data_level: DataLevel = Field(default=DataLevel.D0, description="Associated data class")

__all__ = ["AuditEvent", "AuditEventType"]
