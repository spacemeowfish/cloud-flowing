import asyncio
import hashlib
import json

import pytest
from pydantic import JsonValue

from agent_platform.core.errors import ConfigurationError, SchemaValidationError, ToolNotFoundError, ToolTimeoutError
from agent_platform.core.interfaces import Tool
from agent_platform.core.schema_validator import SchemaValidator
from agent_platform.core.tool_executor import ToolExecutor
from agent_platform.core.tool_registry import ToolRegistry
from agent_platform.models import RiskLevel, ToolCall, ToolMetadata, ToolReceipt


class CountingTool(Tool):
    def __init__(self, delay=0.0):
        self.count = 0
        self.delay = delay

    @property
    def metadata(self):
        return ToolMetadata(
            name="counting",
            description="counter",
            parameters_schema={
                "type": "object",
                "properties": {"value": {"type": "integer", "minimum": 1, "maximum": 10}},
                "required": ["value"],
                "additionalProperties": False,
            },
            risk_level=RiskLevel.R0,
            timeout_seconds=0.05,
        )

    def idempotency_key(self, arguments: dict[str, JsonValue]) -> str:
        return hashlib.sha256(json.dumps(arguments, sort_keys=True).encode()).hexdigest()

    async def execute(self, arguments):
        self.count += 1
        await asyncio.sleep(self.delay)
        return ToolReceipt(tool_name="counting", actual_arguments=arguments, success=True, output_summary="ok")


INVALID_ARGUMENTS = [
    {}, {"value": 0}, {"value": 11}, {"value": -1}, {"value": "1"}, {"value": None}, {"value": True},
    {"value": 1.2}, {"value": []}, {"value": {}}, {"value": 1, "extra": 1}, {"extra": 1},
    {"value": "x"}, {"value": ""}, {"value": -100}, {"value": 100}, {"value": [1]}, {"value": {"x": 1}},
    {"value": False}, {"value": 3, "unknown": "x"}, {"value": 5, "unknown": None},
]


@pytest.mark.parametrize("arguments", INVALID_ARGUMENTS)
def test_schema_rejects_invalid_arguments(arguments):
    with pytest.raises(SchemaValidationError):
        SchemaValidator.validate(arguments, CountingTool().metadata.parameters_schema)


@pytest.mark.asyncio
async def test_idempotency_returns_cached_receipt():
    tool = CountingTool()
    registry = ToolRegistry()
    registry.register(tool)
    registry.freeze()
    executor = ToolExecutor(registry)
    call = ToolCall(task_id="00000000-0000-0000-0000-000000000001", tool_name="counting", arguments={"value": 1})
    first = await executor.execute(call)
    second = await executor.execute(call)
    assert first == second
    assert tool.count == 1


@pytest.mark.asyncio
async def test_timeout_and_cancel():
    tool = CountingTool(delay=1)
    registry = ToolRegistry()
    registry.register(tool)
    registry.freeze()
    executor = ToolExecutor(registry)
    call = ToolCall(task_id="00000000-0000-0000-0000-000000000001", tool_name="counting", arguments={"value": 1})
    with pytest.raises(ToolTimeoutError):
        await executor.execute(call)
    cancellation = asyncio.Event()
    cancellation.set()
    with pytest.raises(asyncio.CancelledError):
        await executor.execute(call, cancellation)


def test_registry_freeze_and_unknown():
    registry = ToolRegistry()
    registry.register(CountingTool())
    registry.freeze()
    with pytest.raises(ConfigurationError):
        registry.register(CountingTool())
    with pytest.raises(ToolNotFoundError):
        registry.get("missing")

