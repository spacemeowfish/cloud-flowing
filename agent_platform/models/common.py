"""Shared enums and JSON-compatible types."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class StrictModel(BaseModel):
    """Base model that rejects unknown fields in protocol payloads."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class DataLevel(StrEnum):
    D0 = "D0"
    D1 = "D1"
    D2 = "D2"
    D3 = "D3"


class RiskLevel(StrEnum):
    R0 = "R0"
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"


class ExecutionTarget(StrEnum):
    LOCAL = "local"
    CLOUD = "cloud"
    QUEUE = "queue"
    REJECTED = "rejected"


class MessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ModelMessage(StrictModel):
    role: MessageRole = Field(..., description="Message author role")
    content: str = Field(..., min_length=1, description="Message text")


JsonObject = dict[str, JsonValue]

__all__ = [
    "DataLevel",
    "ExecutionTarget",
    "JsonObject",
    "MessageRole",
    "ModelMessage",
    "RiskLevel",
    "StrictModel",
]

