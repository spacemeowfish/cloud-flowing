"""OpenAI-compatible cloud model adapter."""

from __future__ import annotations

from collections.abc import Sequence

import httpx
from pydantic import JsonValue

from agent_platform.adapters.structured_response import (
    build_structured_system_prompt,
    effective_max_tokens,
    parse_structured_response,
)
from agent_platform.core.errors import ConfigurationError, ModelError, ModelRateLimitError, ModelTimeoutError
from agent_platform.core.interfaces import ModelAdapter
from agent_platform.models import ModelMessage


class CloudModelAdapter(ModelAdapter):
    """Use one reusable HTTP client and normalize provider failures."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        timeout_seconds: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise ConfigurationError("MODEL_API_KEY is required when MODEL_PROVIDER=cloud")
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._model = model
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
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
            # Intent records are short. This cap prevents small local models from
            # continuing past the closing JSON brace on an otherwise valid response.
            "max_tokens": effective_max_tokens(response_schema, max_tokens),
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        try:
            response = await self._client.post(self._url, json=payload)
        except httpx.TimeoutException as exc:
            raise ModelTimeoutError("Cloud model request timed out") from exc
        except httpx.HTTPError as exc:
            raise ModelError("Cloud model connection failed", retryable=True) from exc

        if response.status_code == 429:
            raise ModelRateLimitError("Cloud model rate limit exceeded")
        if response.status_code >= 500:
            raise ModelError(f"Cloud model service returned {response.status_code}", retryable=True)
        if response.status_code >= 400:
            raise ModelError(f"Cloud model rejected the request with {response.status_code}")

        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ModelError("Cloud model returned invalid structured JSON") from exc
        return parse_structured_response(
            content,
            response_schema,
            error_detail="Cloud model returned invalid structured JSON",
        )

    async def generate_text(
        self,
        messages: Sequence[ModelMessage],
        max_tokens: int = 512,
    ) -> str:
        """Generate provider text without a JSON response format."""

        payload = {
            "model": self._model,
            "messages": [message.model_dump(mode="json") for message in messages],
            "max_tokens": max_tokens,
            "temperature": 0,
        }
        try:
            response = await self._client.post(self._url, json=payload)
        except httpx.TimeoutException as exc:
            raise ModelTimeoutError("Cloud model request timed out") from exc
        except httpx.HTTPError as exc:
            raise ModelError("Cloud model connection failed", retryable=True) from exc
        if response.status_code == 429:
            raise ModelRateLimitError("Cloud model rate limit exceeded")
        if response.status_code >= 500:
            raise ModelError(f"Cloud model service returned {response.status_code}", retryable=True)
        if response.status_code >= 400:
            raise ModelError(f"Cloud model rejected the request with {response.status_code}")
        try:
            content = response.json()["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise TypeError("message.content must be non-empty text")
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ModelError("Cloud model returned an invalid text response") from exc
        return content.strip()

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

if __name__ == "__main__":
    print("CloudModelAdapter requires an injected API key; use project tests for its smoke test.")


__all__ = ["CloudModelAdapter"]
