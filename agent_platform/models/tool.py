"""Tool registration, invocation, and receipt contracts."""

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from pydantic import Field, JsonValue

from agent_platform.models.common import DataLevel, RiskLevel, StrictModel


class ToolMetadata(StrictModel):
    name: str = Field(..., pattern=r"^[a-z][a-z0-9_]*$", description="Unique tool name")
    description: str = Field(..., min_length=1, description="Human-readable capability")
    parameters_schema: dict[str, JsonValue] = Field(..., description="JSON Schema for arguments")
    risk_level: RiskLevel = Field(default=RiskLevel.R0, description="Maximum operation risk")
    data_level: DataLevel = Field(default=DataLevel.D0, description="Typical handled data class")
    timeout_seconds: float = Field(default=10.0, gt=0, le=300, description="Execution timeout")
    retry_budget: int = Field(default=0, ge=0, le=5, description="Retry count for retryable failures")
    requires_network: bool = Field(default=False, description="Whether execution requires network")


class ToolCall(StrictModel):
    task_id: UUID = Field(..., description="Owning task identifier")
    tool_name: str = Field(..., description="Registered tool name")
    arguments: dict[str, JsonValue] = Field(default_factory=dict, description="Validated arguments")
    idempotency_key: str | None = Field(default=None, description="Caller-provided idempotency key")


class ToolReceipt(StrictModel):
    tool_name: str = Field(..., description="Executed tool")
    actual_arguments: dict[str, JsonValue] = Field(default_factory=dict, description="Arguments actually used")
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC), description="Start time in UTC")
    duration_ms: float = Field(default=0.0, ge=0, description="Execution duration")
    success: bool = Field(..., description="Execution result")
    output_summary: str = Field(default="", description="Sanitized result summary")
    output: dict[str, JsonValue] = Field(default_factory=dict, description="Structured result data")
    next_actions: list[str] = Field(default_factory=list, description="Suggested next steps")
    error_code: str | None = Field(default=None, description="Stable failure code")


IdempotencyKeyFactory = Callable[[dict[str, JsonValue]], str]

__all__ = ["IdempotencyKeyFactory", "ToolCall", "ToolMetadata", "ToolReceipt"]
