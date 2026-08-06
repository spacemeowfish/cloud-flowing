"""Model gateway request and response contracts."""

from pydantic import Field, JsonValue

from agent_platform.models.common import ModelMessage, StrictModel


class ModelRequest(StrictModel):
    messages: list[ModelMessage] = Field(..., min_length=1, description="Conversation messages")
    response_schema: dict[str, JsonValue] = Field(default_factory=dict, description="Required JSON schema")
    max_tokens: int = Field(default=512, ge=1, le=8192, description="Maximum generated tokens")


class IntentResult(StrictModel):
    intent: str = Field(..., min_length=1, description="Selected intent identifier")
    arguments: dict[str, JsonValue] = Field(default_factory=dict, description="Extracted tool arguments")
    missing_fields: list[str] = Field(default_factory=list, description="Required arguments still missing")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Intent confidence")


class IntentClassificationResult(StrictModel):
    intent: str = Field(..., min_length=1, description="Selected intent identifier")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Intent confidence")


INTENT_RESPONSE_SCHEMA: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "intent": {
            "type": "string",
            "enum": ["file_open", "knowledge_query", "meeting_process", "reminder_create", "todo_manage", "schedule_manage", "text_polish"],
        },
        "arguments": {"type": "object"},
        "missing_fields": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["intent", "arguments", "missing_fields", "confidence"],
    "additionalProperties": False,
}

__all__ = ["INTENT_RESPONSE_SCHEMA", "IntentClassificationResult", "IntentResult", "ModelRequest"]
