"""HTTP adapter for the official RKLLM OpenAI-compatible server."""

import asyncio
from collections.abc import Sequence

import httpx
from pydantic import ValidationError
from pydantic import JsonValue

from agent_platform.adapters.rkllm_contract import RKLLMChatCompletionRequest, RKLLMChatCompletionResponse
from agent_platform.adapters.structured_response import (
    build_structured_system_prompt,
    effective_max_tokens,
    flatten_rkllm_prompt,
    parse_structured_response,
)
from agent_platform.core.errors import ModelBusyError, ModelError, ModelRateLimitError, ModelTimeoutError
from agent_platform.core.interfaces import ModelAdapter
from agent_platform.models import MessageRole, ModelMessage


class RKLLMModelAdapter(ModelAdapter):
    """Call one local RKLLM server with bounded queueing and strict parsing."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str = "rkllm",
        timeout_seconds: float = 30.0,
        queue_timeout_seconds: float = 2.0,
        max_concurrency: int = 1,
        max_new_tokens: int = 512,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        if max_new_tokens < 1:
            raise ValueError("max_new_tokens must be at least 1")
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._model = model
        self._queue_timeout_seconds = queue_timeout_seconds
        self._max_new_tokens = max_new_tokens
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            headers={"Content-Type": "application/json", "Authorization": "not_required"},
        )

    async def generate(
        self,
        messages: Sequence[ModelMessage],
        response_schema: dict[str, JsonValue],
        max_tokens: int = 512,
    ) -> dict[str, JsonValue]:
        system_content = build_structured_system_prompt(response_schema)
        flattened_prompt = flatten_rkllm_prompt(system_content, messages)
        request = RKLLMChatCompletionRequest(
            model=self._model,
            messages=[{"role": MessageRole.USER, "content": flattened_prompt}],
            max_tokens=effective_max_tokens(response_schema, max_tokens, self._max_new_tokens),
        )

        try:
            await asyncio.wait_for(self._semaphore.acquire(), timeout=self._queue_timeout_seconds)
        except TimeoutError as exc:
            raise ModelBusyError("RKLLM request queue is full") from exc

        try:
            try:
                response = await self._client.post(self._url, json=request.model_dump(mode="json"))
            except httpx.TimeoutException as exc:
                raise ModelTimeoutError("RKLLM model request timed out") from exc
            except httpx.HTTPError as exc:
                raise ModelError("RKLLM model connection failed", retryable=True) from exc

            if response.status_code == 429:
                raise ModelRateLimitError("RKLLM model rate limit exceeded")
            if response.status_code == 503:
                raise ModelBusyError("RKLLM server is busy")
            if response.status_code >= 500:
                raise ModelError(f"RKLLM model service returned {response.status_code}", retryable=True)
            if response.status_code >= 400:
                raise ModelError(f"RKLLM model rejected the request with {response.status_code}")

            try:
                completion = RKLLMChatCompletionResponse.model_validate(response.json())
                content = completion.choices[0].message.content
            except (ValueError, IndexError, ValidationError) as exc:
                raise ModelError("RKLLM model returned an invalid protocol response") from exc
            return parse_structured_response(
                content,
                response_schema,
                error_detail="RKLLM model returned invalid structured JSON",
            )
        finally:
            self._semaphore.release()

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()


__all__ = ["RKLLMModelAdapter"]
