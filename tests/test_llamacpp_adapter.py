import json

import httpx
import pytest

from agent_platform.adapters.llamacpp_adapter import LlamaCppModelAdapter
from agent_platform.core.errors import ModelBusyError, ModelError, ModelRateLimitError, ModelTimeoutError
from agent_platform.models import MessageRole, ModelMessage


SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}


def adapter(handler, **kwargs):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return LlamaCppModelAdapter(base_url="http://127.0.0.1:8080/v1", model="test", client=client, **kwargs)


@pytest.mark.asyncio
async def test_llamacpp_payload_and_structured_response():
    async def handler(request):
        payload = json.loads(request.content)
        assert request.url.path == "/v1/chat/completions"
        assert payload["stream"] is False
        assert payload["temperature"] == 0
        assert payload["response_format"] == {"type": "json_object"}
        assert payload["max_tokens"] == 300
        assert payload["messages"][0]["role"] == "system"
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"answer":"ok"}'}}]})

    model = adapter(handler, max_new_tokens=300)
    result = await model.generate([ModelMessage(role=MessageRole.USER, content="x")], SCHEMA, 512)
    assert result == {"answer": "ok"}
    await model.close()


@pytest.mark.asyncio
async def test_llamacpp_free_text_omits_schema_prompt_and_response_format():
    async def handler(request):
        payload = json.loads(request.content)
        assert "response_format" not in payload
        assert payload["messages"] == [{"role": "user", "content": "你好"}]
        assert payload["max_tokens"] == 128
        return httpx.Response(200, json={"choices": [{"message": {"content": "  你好！  "}}]})

    model = adapter(handler, max_new_tokens=128)
    result = await model.generate_text([ModelMessage(role=MessageRole.USER, content="你好")], 512)
    assert result == "你好！"
    await model.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("status,error", [(429, ModelRateLimitError), (503, ModelBusyError), (500, ModelError), (400, ModelError)])
async def test_llamacpp_normalizes_http_errors(status, error):
    async def handler(request):
        return httpx.Response(status, text="error")

    model = adapter(handler)
    with pytest.raises(error):
        await model.generate([ModelMessage(role=MessageRole.USER, content="x")], SCHEMA)
    await model.close()


@pytest.mark.asyncio
async def test_llamacpp_normalizes_timeout():
    async def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    model = adapter(handler)
    with pytest.raises(ModelTimeoutError):
        await model.generate([ModelMessage(role=MessageRole.USER, content="x")], SCHEMA)
    await model.close()


@pytest.mark.asyncio
async def test_llamacpp_rejects_invalid_protocol():
    async def handler(request):
        return httpx.Response(200, json={"choices": []})

    model = adapter(handler)
    with pytest.raises(ModelError, match="invalid protocol"):
        await model.generate([ModelMessage(role=MessageRole.USER, content="x")], SCHEMA)
    await model.close()
