"""Native Ollama adapter for local structured model calls."""

from __future__ import annotations

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
    hostname = urlparse(base_url).hostname
    return hostname in {"127.0.0.1", "localhost", "::1"}


class OllamaModelAdapter(ModelAdapter):
    """Call Ollama's native API and return schema-validated JSON."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout_seconds: float = 120.0,
        thinking_enabled: bool = False,
        keep_alive: str = "10m",
        max_new_tokens: int = 512,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not model.strip():
            raise ValueError("model must not be empty")
        if max_new_tokens < 1:
            raise ValueError("max_new_tokens must be at least 1")
        self._url = f"{base_url.rstrip('/')}/api/chat"
        self._model = model
        self._thinking_enabled = thinking_enabled
        self._keep_alive = keep_alive
        self._max_new_tokens = max_new_tokens
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            headers={"Content-Type": "application/json"},
            # Windows system proxies can otherwise intercept 127.0.0.1.
            trust_env=not _is_loopback_url(base_url),
        )

    async def generate(
        self,
        messages: Sequence[ModelMessage],
        response_schema: dict[str, JsonValue],
        max_tokens: int = 512,
    ) -> dict[str, JsonValue]:
        system_content = build_structured_system_prompt(response_schema)
        payload = {
            "model": self._model,
            "messages": [{"role": "system", "content": system_content}]
            + [message.model_dump(mode="json") for message in messages],
            "stream": False,
            "think": self._thinking_enabled,
            "format": "json",
            "keep_alive": self._keep_alive,
            "options": {
                "temperature": 0,
                "num_predict": effective_max_tokens(response_schema, max_tokens, self._max_new_tokens),
            },
        }
        try:
            response = await self._client.post(self._url, json=payload)
        except httpx.TimeoutException as exc:
            raise ModelTimeoutError("Ollama model request timed out") from exc
        except httpx.HTTPError as exc:
            raise ModelError("Ollama model connection failed", retryable=True) from exc

        if response.status_code == 429:
            raise ModelRateLimitError("Ollama model rate limit exceeded")
        if response.status_code == 503:
            raise ModelBusyError("Ollama server is busy")
        if response.status_code >= 500:
            raise ModelError(f"Ollama model service returned {response.status_code}", retryable=True)
        if response.status_code >= 400:
            raise ModelError(f"Ollama model rejected the request with {response.status_code}")

        try:
            body = response.json()
            message = body["message"]
            content = message["content"]
            if not isinstance(content, (str, dict)):
                raise TypeError("message.content must be text or an object")
        except (ValueError, KeyError, TypeError) as exc:
            raise ModelError("Ollama model returned an invalid protocol response") from exc
        return parse_structured_response(
            content,
            response_schema,
            error_detail="Ollama model returned invalid structured JSON",
        )

    async def generate_text(
        self,
        messages: Sequence[ModelMessage],
        max_tokens: int = 512,
    ) -> str:
        """Use Ollama's native free-text mode without ``format=json``."""

        payload = {
            "model": self._model,
            "messages": [message.model_dump(mode="json") for message in messages],
            "stream": False,
            "think": self._thinking_enabled,
            "keep_alive": self._keep_alive,
            "options": {
                "temperature": 0,
                "num_predict": min(max_tokens, self._max_new_tokens),
            },
        }
        try:
            response = await self._client.post(self._url, json=payload)
        except httpx.TimeoutException as exc:
            raise ModelTimeoutError("Ollama model request timed out") from exc
        except httpx.HTTPError as exc:
            raise ModelError("Ollama model connection failed", retryable=True) from exc

        if response.status_code == 429:
            raise ModelRateLimitError("Ollama model rate limit exceeded")
        if response.status_code == 503:
            raise ModelBusyError("Ollama server is busy")
        if response.status_code >= 500:
            raise ModelError(f"Ollama model service returned {response.status_code}", retryable=True)
        if response.status_code >= 400:
            raise ModelError(f"Ollama model rejected the request with {response.status_code}")
        try:
            content = response.json()["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise TypeError("message.content must be non-empty text")
        except (ValueError, KeyError, TypeError) as exc:
            raise ModelError("Ollama model returned an invalid text response") from exc
        return content.strip()

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()


__all__ = ["OllamaModelAdapter"]
