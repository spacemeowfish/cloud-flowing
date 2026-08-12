"""OpenAI-compatible adapter for a local llama.cpp server."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from urllib.parse import urlparse

import httpx
from pydantic import JsonValue

from agent_platform.adapters.structured_response import (
    build_structured_system_prompt,
    effective_max_tokens,
    parse_structured_response,
)
from agent_platform.core.errors import ModelBusyError, ModelError, ModelRateLimitError, ModelTimeoutError
from agent_platform.core.interfaces import ModelAdapter
from agent_platform.models import ModelMessage


def _is_loopback_url(base_url: str) -> bool:
    return urlparse(base_url).hostname in {"127.0.0.1", "localhost", "::1"}


class LlamaCppModelAdapter(ModelAdapter):
    """Call one local llama.cpp server with bounded serial queueing."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout_seconds: float = 120.0,
        queue_timeout_seconds: float = 2.0,
        max_concurrency: int = 1,
        max_new_tokens: int = 512,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not model.strip():
            raise ValueError("model must not be empty")
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
            headers={"Content-Type": "application/json"},
            trust_env=not _is_loopback_url(base_url),
        )

    async def generate(
        self,
        messages: Sequence[ModelMessage],
        response_schema: dict[str, JsonValue],
        max_tokens: int = 512,
    ) -> dict[str, JsonValue]:
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": build_structured_system_prompt(response_schema)},
                *[message.model_dump(mode="json") for message in messages],
            ],
            "stream": False,
            "temperature": 0,
            "max_tokens": effective_max_tokens(response_schema, max_tokens, self._max_new_tokens),
            "response_format": {"type": "json_object"},
        }
        content = await self._completion_content(payload)
        return parse_structured_response(
            content,
            response_schema,
            error_detail="llama.cpp model returned invalid structured JSON",
        )

    async def generate_text(
        self,
        messages: Sequence[ModelMessage],
        max_tokens: int = 512,
    ) -> str:
        """Generate plain content without a JSON response format or Schema prompt."""

        payload = {
            "model": self._model,
            "messages": [message.model_dump(mode="json") for message in messages],
            "stream": False,
            "temperature": 0,
            "max_tokens": min(max_tokens, self._max_new_tokens),
        }
        content = await self._completion_content(payload)
        if not isinstance(content, str) or not content.strip():
            raise ModelError("llama.cpp model returned an invalid text response")
        return content.strip()

    async def _completion_content(self, payload: dict[str, object]) -> str | dict[str, object]:
        """Submit one bounded request and return the protocol-level message content."""

        try:
            await asyncio.wait_for(self._semaphore.acquire(), timeout=self._queue_timeout_seconds)
        except TimeoutError as exc:
            raise ModelBusyError("llama.cpp request queue is full") from exc
        try:
            try:
                response = await self._client.post(self._url, json=payload)
            except httpx.TimeoutException as exc:
                raise ModelTimeoutError("llama.cpp model request timed out") from exc
            except httpx.HTTPError as exc:
                raise ModelError("llama.cpp model connection failed", retryable=True) from exc

            if response.status_code == 429:
                raise ModelRateLimitError("llama.cpp model rate limit exceeded")
            if response.status_code == 503:
                raise ModelBusyError("llama.cpp server is busy")
            if response.status_code >= 500:
                raise ModelError(f"llama.cpp model service returned {response.status_code}", retryable=True)
            if response.status_code >= 400:
                raise ModelError(f"llama.cpp model rejected the request with {response.status_code}")
            try:
                body = response.json()
                content = body["choices"][0]["message"]["content"]
                if not isinstance(content, (str, dict)):
                    raise TypeError("message.content must be text or an object")
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                raise ModelError("llama.cpp model returned an invalid protocol response") from exc
            return content
        finally:
            self._semaphore.release()

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()


__all__ = ["LlamaCppModelAdapter"]
