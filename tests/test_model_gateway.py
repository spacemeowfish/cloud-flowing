import json

import httpx
import pytest

from agent_platform.adapters.cloud_adapter import CloudModelAdapter
from agent_platform.adapters.mock_adapter import MockModelAdapter
from agent_platform.core.tool_registry import ToolRegistry
from agent_platform.core.errors import ModelBusyError, ModelError, ModelRateLimitError, ModelSchemaError, ModelTimeoutError
from agent_platform.core.model_gateway import ModelGateway
from agent_platform.models import DataLevel, INTENT_RESPONSE_SCHEMA, MessageRole, ModelMessage, ToolMetadata, argument_extraction_contract, build_model_acceptance_schema


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "intent"),
    [
        ("打开年度报告", "file_open"),
        ("查询产品保修期", "knowledge_query"),
        ("提醒我30分钟后开会", "reminder_create"),
        ("添加待办 提交报告", "todo_manage"),
        ("创建日程 明天下午2点开会", "schedule_manage"),
        ("润色：明天提交", "text_polish"),
        (r"整理会议纪要 C:\demo\meeting.txt", "meeting_process"),
        ("1+1等于多少？", "general_chat"),
    ],
)
async def test_mock_adapter_supported_intents(text, intent):
    result = await MockModelAdapter().generate(
        [ModelMessage(role=MessageRole.USER, content=text)], INTENT_RESPONSE_SCHEMA
    )
    assert result["intent"] == intent
    assert set(result) == {"intent", "arguments", "missing_fields", "confidence"}


def _cloud_adapter(handler):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return CloudModelAdapter(base_url="https://example.test/v1", model="test", api_key="secret", client=client)


@pytest.mark.asyncio
async def test_cloud_adapter_valid_json():
    async def handler(request):
        payload = {"intent": "knowledge_query", "arguments": {"query": "x"}, "missing_fields": [], "confidence": 1}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}]})

    adapter = _cloud_adapter(handler)
    result = await adapter.generate([ModelMessage(role=MessageRole.USER, content="x")], INTENT_RESPONSE_SCHEMA)
    assert result["intent"] == "knowledge_query"
    await adapter._client.aclose()


@pytest.mark.asyncio
async def test_cloud_adapter_free_text_omits_json_response_format():
    async def handler(request):
        payload = json.loads(request.content)
        assert "response_format" not in payload
        assert payload["messages"] == [{"role": "user", "content": "hello"}]
        return httpx.Response(200, json={"choices": [{"message": {"content": "  hi  "}}]})

    adapter = _cloud_adapter(handler)
    assert await adapter.generate_text([ModelMessage(role=MessageRole.USER, content="hello")]) == "hi"
    await adapter._client.aclose()


def _acceptance_registry() -> ToolRegistry:
    class MetadataTool:
        def __init__(self, name, required, properties):
            self._metadata = ToolMetadata(
                name=name,
                description=name,
                parameters_schema={
                    "type": "object",
                    "properties": properties,
                    "required": required,
                    "additionalProperties": False,
                },
            )

        @property
        def metadata(self):
            return self._metadata

    registry = ToolRegistry()
    specs = {
        "file_open": (["query"], {"query": {"type": "string"}}),
        "general_chat": (["text"], {"text": {"type": "string"}}),
        "knowledge_query": (["query"], {"query": {"type": "string"}}),
        "meeting_process": (["source_path"], {"source_path": {"type": "string"}}),
        "reminder_create": (["action"], {"action": {"type": "string"}}),
        "todo_manage": (["action"], {"action": {"type": "string"}}),
        "schedule_manage": (["action"], {"action": {"type": "string"}}),
        "text_polish": (["operation", "text"], {"operation": {"type": "string"}, "text": {"type": "string"}}),
    }
    for name, (required, properties) in specs.items():
        registry.register(MetadataTool(name, required, properties))  # type: ignore[arg-type]
    registry.freeze()
    return registry


@pytest.mark.asyncio
async def test_cloud_adapter_accepts_compatibility_alias_with_compact_few_shot_prompt():
    acceptance_schema = build_model_acceptance_schema(_acceptance_registry())

    async def handler(request):
        request_payload = json.loads(request.content)
        system_prompt = request_payload["messages"][0]["content"]
        assert "用户：取消提醒 12" in system_prompt
        assert "operation=draft" in system_prompt
        assert "Schema: {" not in system_prompt
        assert request_payload["max_tokens"] == 192
        payload = {
            "intent": "knowledge_query",
            "arguments": {"question": "产品保修期"},
            "missing_fields": [],
            "confidence": 1,
        }
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}]})

    adapter = _cloud_adapter(handler)
    result = await adapter.generate(
        [ModelMessage(role=MessageRole.USER, content="查询产品保修期")], acceptance_schema
    )
    assert result["arguments"] == {"question": "产品保修期"}
    await adapter._client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("status,exception", [(429, ModelRateLimitError), (500, ModelError), (400, ModelError)])
async def test_cloud_adapter_http_errors(status, exception):
    async def handler(request):
        return httpx.Response(status, text="error")

    adapter = _cloud_adapter(handler)
    with pytest.raises(exception):
        await adapter.generate([ModelMessage(role=MessageRole.USER, content="x")], INTENT_RESPONSE_SCHEMA)
    await adapter._client.aclose()


@pytest.mark.asyncio
async def test_cloud_adapter_invalid_json():
    async def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "not-json"}}]})

    adapter = _cloud_adapter(handler)
    with pytest.raises(ModelError):
        await adapter.generate([ModelMessage(role=MessageRole.USER, content="x")], INTENT_RESPONSE_SCHEMA)
    await adapter._client.aclose()


@pytest.mark.asyncio
async def test_cloud_adapter_timeout():
    async def handler(request):
        raise httpx.ReadTimeout("timeout", request=request)

    adapter = _cloud_adapter(handler)
    with pytest.raises(ModelTimeoutError):
        await adapter.generate([ModelMessage(role=MessageRole.USER, content="x")], INTENT_RESPONSE_SCHEMA)
    await adapter._client.aclose()


class _RecordingAdapter:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = 0
        self.closed = False

    async def generate(self, messages, response_schema, max_tokens=512):
        del messages, response_schema, max_tokens
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result

    async def close(self):
        self.closed = True


class _SequenceRecordingAdapter:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    async def generate(self, messages, response_schema, max_tokens=512):
        self.calls.append((list(messages), response_schema, max_tokens))
        return self.results.pop(0)

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_interpret_uses_pre_route_and_only_selected_intent_schema():
    adapter = _SequenceRecordingAdapter(
        [
            {
                "arguments": {"action": "create"},
                "missing_fields": [],
            }
        ]
    )
    gateway = ModelGateway(adapter)

    result = await gateway.interpret(
        "提醒我30分钟后开会",
        build_model_acceptance_schema(_acceptance_registry()),
    )

    assert result.intent.intent == "reminder_create"
    assert result.route_source == "pre_route:explicit_reminder"
    assert result.model_calls == 1
    assert argument_extraction_contract(adapter.calls[0][1])[0] == "reminder_create"


@pytest.mark.asyncio
async def test_interpret_falls_back_to_model_classification_for_ambiguous_request():
    adapter = _SequenceRecordingAdapter(
        [
            {"intent": "knowledge_query", "confidence": 0.72},
            {
                "arguments": {"query": "帮我处理一下这个事情"},
                "missing_fields": [],
            },
        ]
    )
    gateway = ModelGateway(adapter)

    result = await gateway.interpret(
        "帮我处理一下这个事情",
        build_model_acceptance_schema(_acceptance_registry()),
    )

    assert result.route_source == "model_classification"
    assert result.model_calls == 2
    assert len(adapter.calls) == 2


@pytest.mark.asyncio
async def test_interpret_repairs_one_complete_schema_invalid_output_without_relaxing_schema():
    adapter = _SequenceRecordingAdapter(
        [
            {
                "arguments": {"action": "cancel", "start_text": "12"},
                "missing_fields": [],
            },
            {
                "arguments": {"action": "cancel"},
                "missing_fields": [],
            },
        ]
    )
    gateway = ModelGateway(adapter)

    result = await gateway.interpret(
        "取消日程 12",
        build_model_acceptance_schema(_acceptance_registry()),
    )

    assert result.schema_repaired is True
    assert result.model_calls == 2
    assert len(adapter.calls[1][0]) == 2
    assert "校验错误" in adapter.calls[1][0][-1].content
    assert adapter.calls[0][1] == adapter.calls[1][1]


@pytest.mark.asyncio
async def test_interpret_stops_after_one_failed_schema_repair():
    invalid = {
        "arguments": {"action": "cancel", "start_text": "12"},
        "missing_fields": [],
    }
    adapter = _SequenceRecordingAdapter([invalid, invalid])
    gateway = ModelGateway(adapter)

    with pytest.raises(ModelSchemaError):
        await gateway.interpret("取消日程 12", build_model_acceptance_schema(_acceptance_registry()))

    assert len(adapter.calls) == 2


@pytest.mark.asyncio
async def test_interpret_does_not_repair_malformed_json_model_error():
    adapter = _RecordingAdapter(error=ModelError("invalid JSON"))
    gateway = ModelGateway(adapter)

    with pytest.raises(ModelError, match="invalid JSON"):
        await gateway.interpret("取消日程 12", build_model_acceptance_schema(_acceptance_registry()))

    assert adapter.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("level", [DataLevel.D0, DataLevel.D1])
async def test_model_gateway_falls_back_only_for_retryable_low_classification(level):
    primary = _RecordingAdapter(error=ModelBusyError("busy"))
    fallback = _RecordingAdapter(result={"ok": True})
    gateway = ModelGateway(primary, fallback_adapter=fallback)
    result = await gateway.generate(
        [ModelMessage(role=MessageRole.USER, content="x")],
        {"type": "object"},
        data_level=level,
    )
    assert result == {"ok": True}
    assert primary.calls == fallback.calls == 1
    await gateway.close()
    assert primary.closed and fallback.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("level", [None, DataLevel.D2, DataLevel.D3])
async def test_model_gateway_never_falls_back_for_unknown_or_sensitive_classification(level):
    primary = _RecordingAdapter(error=ModelBusyError("busy"))
    fallback = _RecordingAdapter(result={"ok": True})
    gateway = ModelGateway(primary, fallback_adapter=fallback)
    with pytest.raises(ModelBusyError):
        await gateway.generate(
            [ModelMessage(role=MessageRole.USER, content="x")],
            {"type": "object"},
            data_level=level,
        )
    assert fallback.calls == 0
    await gateway.close()


@pytest.mark.asyncio
async def test_model_gateway_does_not_fallback_for_non_retryable_model_error():
    primary = _RecordingAdapter(error=ModelError("invalid JSON"))
    fallback = _RecordingAdapter(result={"ok": True})
    gateway = ModelGateway(primary, fallback_adapter=fallback)
    with pytest.raises(ModelError, match="invalid JSON"):
        await gateway.generate(
            [ModelMessage(role=MessageRole.USER, content="x")],
            {"type": "object"},
            data_level=DataLevel.D0,
        )
    assert fallback.calls == 0
    await gateway.close()
