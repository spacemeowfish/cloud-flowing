import json

import httpx
import pytest

from agent_platform.adapters.ollama_adapter import OllamaModelAdapter
from agent_platform.config import Settings
from agent_platform.core.errors import ModelBusyError, ModelError, ModelRateLimitError, ModelTimeoutError
from agent_platform.core.model_gateway import ModelGateway
from agent_platform.models import INTENT_RESPONSE_SCHEMA, MessageRole, ModelMessage


VALID_INTENT = {
    "intent": "knowledge_query",
    "arguments": {"query": "保修期"},
    "missing_fields": [],
    "confidence": 1,
}


def _response(content: object, *, thinking: str | None = None) -> dict[str, object]:
    message: dict[str, object] = {"role": "assistant", "content": content}
    if thinking is not None:
        message["thinking"] = thinking
    return {"model": "test", "message": message, "done": True, "done_reason": "stop"}


def _adapter(handler, **kwargs):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return (
        OllamaModelAdapter(base_url="http://ollama.test", model="test", client=client, **kwargs),
        client,
    )


@pytest.mark.asyncio
async def test_ollama_adapter_uses_native_non_thinking_contract():
    async def handler(request):
        assert request.url.path == "/api/chat"
        payload = json.loads(request.content)
        assert payload["model"] == "test"
        assert payload["stream"] is False
        assert payload["think"] is False
        assert payload["format"] == "json"
        assert payload["keep_alive"] == "10m"
        assert payload["options"] == {"temperature": 0, "num_predict": 192}
        assert payload["messages"][0]["role"] == "system"
        return httpx.Response(200, json=_response(json.dumps(VALID_INTENT, ensure_ascii=False)))

    adapter, client = _adapter(handler)
    result = await adapter.generate(
        [ModelMessage(role=MessageRole.USER, content="查询保修期")], INTENT_RESPONSE_SCHEMA
    )
    assert result == VALID_INTENT
    await client.aclose()


@pytest.mark.asyncio
async def test_ollama_free_text_does_not_request_json_format():
    async def handler(request):
        payload = json.loads(request.content)
        assert "format" not in payload
        assert payload["messages"] == [{"role": "user", "content": "你好"}]
        assert payload["options"]["num_predict"] == 64
        return httpx.Response(200, json=_response("  你好！  "))

    adapter, client = _adapter(handler, max_new_tokens=64)
    assert await adapter.generate_text([ModelMessage(role=MessageRole.USER, content="你好")]) == "你好！"
    await client.aclose()


@pytest.mark.asyncio
async def test_ollama_adapter_can_enable_thinking_but_only_parses_final_content():
    async def handler(request):
        payload = json.loads(request.content)
        assert payload["think"] is True
        return httpx.Response(
            200,
            json=_response(json.dumps(VALID_INTENT, ensure_ascii=False), thinking="private reasoning"),
        )

    adapter, client = _adapter(handler, thinking_enabled=True)
    result = await adapter.generate(
        [ModelMessage(role=MessageRole.USER, content="查询保修期")], INTENT_RESPONSE_SCHEMA
    )
    assert result == VALID_INTENT
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "exception", "retryable"),
    [
        (400, ModelError, False),
        (429, ModelRateLimitError, True),
        (500, ModelError, True),
        (503, ModelBusyError, True),
    ],
)
async def test_ollama_adapter_normalizes_http_failures(status, exception, retryable):
    async def handler(request):
        return httpx.Response(status, json={"error": "failure"})

    adapter, client = _adapter(handler)
    with pytest.raises(exception) as captured:
        await adapter.generate([ModelMessage(role=MessageRole.USER, content="x")], INTENT_RESPONSE_SCHEMA)
    assert captured.value.retryable is retryable
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"unexpected": True}, _response(123), _response("not-json")])
async def test_ollama_adapter_rejects_invalid_protocol_or_structured_content(body):
    async def handler(request):
        return httpx.Response(200, json=body)

    adapter, client = _adapter(handler)
    with pytest.raises(ModelError):
        await adapter.generate([ModelMessage(role=MessageRole.USER, content="x")], INTENT_RESPONSE_SCHEMA)
    await client.aclose()


@pytest.mark.asyncio
async def test_ollama_adapter_normalizes_timeout():
    async def handler(request):
        raise httpx.ReadTimeout("timeout", request=request)

    adapter, client = _adapter(handler)
    with pytest.raises(ModelTimeoutError):
        await adapter.generate([ModelMessage(role=MessageRole.USER, content="x")], INTENT_RESPONSE_SCHEMA)
    await client.aclose()


@pytest.mark.asyncio
async def test_model_gateway_builds_ollama_provider():
    gateway = ModelGateway.from_settings(
        Settings(
            model_provider="ollama",
            model_name="qwen2.5:3b",
            ollama_base_url="http://127.0.0.1:11434",
        )
    )
    assert isinstance(gateway._adapter, OllamaModelAdapter)
    await gateway.close()
