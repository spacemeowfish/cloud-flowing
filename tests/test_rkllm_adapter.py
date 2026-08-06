import asyncio
import json
import time

import httpx
import pytest

from agent_platform.adapters.rkllm_adapter import RKLLMModelAdapter
from agent_platform.core.errors import ModelBusyError, ModelError, ModelRateLimitError, ModelTimeoutError
from agent_platform.models import INTENT_RESPONSE_SCHEMA, MessageRole, ModelMessage


VALID_INTENT = {
    "intent": "knowledge_query",
    "arguments": {"query": "保修期"},
    "missing_fields": [],
    "confidence": 1,
}


def _completion(content: str) -> dict[str, object]:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "rkllm",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "logprobs": None,
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def _adapter(handler, **kwargs):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return RKLLMModelAdapter(base_url="http://rkllm.test/v1", client=client, **kwargs), client


@pytest.mark.asyncio
async def test_rkllm_adapter_uses_frozen_contract_and_shared_intent_cap():
    async def handler(request):
        assert request.url.path == "/v1/chat/completions"
        payload = json.loads(request.content)
        assert payload["stream"] is False
        assert payload["enable_thinking"] is False
        assert payload["max_tokens"] == 192
        assert len(payload["messages"]) == 1
        assert "CURRENT_CONVERSATION_JSON:" in payload["messages"][0]["content"]
        return httpx.Response(200, json=_completion(json.dumps(VALID_INTENT, ensure_ascii=False)))

    adapter, client = _adapter(handler, max_new_tokens=512)
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
async def test_rkllm_adapter_normalizes_http_failures(status, exception, retryable):
    async def handler(request):
        return httpx.Response(status, json={"error": {"message": "failure"}})

    adapter, client = _adapter(handler)
    with pytest.raises(exception) as captured:
        await adapter.generate([ModelMessage(role=MessageRole.USER, content="x")], INTENT_RESPONSE_SCHEMA)
    assert captured.value.retryable is retryable
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"unexpected": True}, _completion("not-json")])
async def test_rkllm_adapter_rejects_invalid_protocol_or_structured_content(body):
    async def handler(request):
        return httpx.Response(200, json=body)

    adapter, client = _adapter(handler)
    with pytest.raises(ModelError):
        await adapter.generate([ModelMessage(role=MessageRole.USER, content="x")], INTENT_RESPONSE_SCHEMA)
    await client.aclose()


@pytest.mark.asyncio
async def test_rkllm_adapter_normalizes_timeout():
    async def handler(request):
        raise httpx.ReadTimeout("timeout", request=request)

    adapter, client = _adapter(handler)
    with pytest.raises(ModelTimeoutError):
        await adapter.generate([ModelMessage(role=MessageRole.USER, content="x")], INTENT_RESPONSE_SCHEMA)
    await client.aclose()


@pytest.mark.asyncio
async def test_rkllm_adapter_bounds_the_waiting_queue():
    started = asyncio.Event()
    release = asyncio.Event()

    async def handler(request):
        started.set()
        await release.wait()
        return httpx.Response(200, json=_completion(json.dumps(VALID_INTENT)))

    adapter, client = _adapter(handler, queue_timeout_seconds=0.01)
    first = asyncio.create_task(
        adapter.generate([ModelMessage(role=MessageRole.USER, content="one")], INTENT_RESPONSE_SCHEMA)
    )
    await started.wait()
    with pytest.raises(ModelBusyError):
        await adapter.generate([ModelMessage(role=MessageRole.USER, content="two")], INTENT_RESPONSE_SCHEMA)
    release.set()
    assert await first == VALID_INTENT
    await client.aclose()


@pytest.mark.asyncio
async def test_rkllm_adapter_propagates_cancellation_and_releases_slot():
    started = asyncio.Event()

    async def handler(request):
        started.set()
        await asyncio.Event().wait()

    adapter, client = _adapter(handler, queue_timeout_seconds=0.1)
    task = asyncio.create_task(
        adapter.generate([ModelMessage(role=MessageRole.USER, content="cancel")], INTENT_RESPONSE_SCHEMA)
    )
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert adapter._semaphore.locked() is False
    await client.aclose()
