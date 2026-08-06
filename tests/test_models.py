"""Protocol round-trip tests for every model module."""

from datetime import datetime
from uuid import uuid4

import pytest

from agent_platform.models import (
    AuditEvent,
    AuditEventType,
    ClassificationResult,
    DataLevel,
    ErrorResponse,
    EvaluationCase,
    EvaluationMetrics,
    EvaluationReport,
    ExecutionTarget,
    IntentResult,
    MessageRole,
    ModelMessage,
    ModelRequest,
    PolicyContext,
    PolicyDecision,
    ResourceMetrics,
    RiskLevel,
    RoutingDecision,
    RoutingRequest,
    TaskCreate,
    TaskRecord,
    ToolCall,
    ToolMetadata,
    ToolReceipt,
)


MODEL_INSTANCES = [
    ModelMessage(role=MessageRole.USER, content="hello"),
    ModelRequest(messages=[ModelMessage(role=MessageRole.USER, content="hello")]),
    IntentResult(intent="knowledge_query", confidence=0.9),
    TaskCreate(text="query"),
    TaskRecord(request_text="query"),
    ToolMetadata(name="sample", description="sample", parameters_schema={"type": "object"}),
    ToolCall(task_id=uuid4(), tool_name="sample"),
    ToolReceipt(tool_name="sample", success=True),
    ClassificationResult(redacted_text="safe"),
    PolicyContext(role="user", data_domain="personal", risk_level=RiskLevel.R0, data_level=DataLevel.D0, action="read"),
    PolicyDecision(allowed=True, reason="ok"),
    ResourceMetrics(),
    RoutingRequest(tool_name="sample", local_tool_available=True, data_level=DataLevel.D0),
    RoutingDecision(target=ExecutionTarget.LOCAL, reason="ok"),
    AuditEvent(task_id=uuid4(), event_type=AuditEventType.INPUT_RECEIVED),
    ErrorResponse(code="error", message="message"),
    EvaluationCase(id="1", input_text="hello", expected_intent="sample", expected_tool="sample"),
    EvaluationMetrics(total=1),
    EvaluationReport(metrics=EvaluationMetrics(total=1)),
]


@pytest.mark.parametrize("instance", MODEL_INSTANCES, ids=lambda value: type(value).__name__)
def test_model_json_round_trip(instance):
    restored = type(instance).model_validate_json(instance.model_dump_json())
    assert restored == instance


def test_unknown_fields_are_rejected():
    with pytest.raises(Exception):
        TaskCreate.model_validate({"text": "hello", "unknown": True})

