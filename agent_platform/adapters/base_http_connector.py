"""Reusable HTTP connector with token bucket, retries, and circuit degradation."""

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx
from pydantic import JsonValue

from agent_platform.core.errors import AgentPlatformError


class ConnectorError(AgentPlatformError):
    code = "connector_error"


class ConnectorRateLimitError(ConnectorError):
    code = "connector_rate_limited"
    retryable = True


@dataclass(frozen=True)
class ConnectorConfig:
    name: str
    rate_per_second: float = 5.0
    burst: int = 5
    timeout_seconds: float = 5.0
    retry_budget: int = 2
    degraded_seconds: float = 30.0
    fallback: str = "fail"


class TokenBucket:
    """Coroutine-safe lazy-refill token bucket."""

    def __init__(self, rate: float, capacity: int) -> None:
        self._rate = rate
        self._capacity = float(capacity)
        self._tokens = float(capacity)
        self._updated_at = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, *, wait: bool = False) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                elapsed = now - self._updated_at
                self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
                self._updated_at = now
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                delay = (1 - self._tokens) / self._rate
            if not wait:
                raise ConnectorRateLimitError("Connector token bucket is empty")
            await asyncio.sleep(delay)


class BaseHttpConnector(ABC):
    """Keep transport and resilience mechanics out of concrete connectors."""

    def __init__(self, config: ConnectorConfig, client: httpx.AsyncClient | None = None) -> None:
        self.config = config
        self._bucket = TokenBucket(config.rate_per_second, config.burst)
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(config.timeout_seconds))
        self._consecutive_failures = 0
        self._degraded_until = 0.0

    @abstractmethod
    def authenticate(self, request: dict[str, JsonValue]) -> dict[str, JsonValue]:
        """Add credentials without exposing them to logs."""

    @abstractmethod
    async def request(self, parameters: dict[str, JsonValue]) -> dict[str, JsonValue]:
        """Perform one provider request and return structured data."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Return provider availability without mutating remote state."""

    async def execute(self, parameters: dict[str, JsonValue]) -> dict[str, JsonValue]:
        await self._bucket.acquire(wait=False)
        now = time.monotonic()
        if now < self._degraded_until:
            return await self.degraded_response(parameters)

        last_error: Exception | None = None
        for attempt in range(self.config.retry_budget + 1):
            try:
                result = await self.request(self.authenticate(dict(parameters)))
                self._consecutive_failures = 0
                self._degraded_until = 0.0
                return result
            except ConnectorRateLimitError:
                raise
            except Exception as exc:
                last_error = exc
                self._consecutive_failures += 1
                if attempt < self.config.retry_budget:
                    await asyncio.sleep(min(0.05 * (2**attempt), 1.0))
        if self._consecutive_failures >= self.config.retry_budget + 1:
            self._degraded_until = time.monotonic() + self.config.degraded_seconds
            return await self.degraded_response(parameters)
        raise ConnectorError(f"Connector failed: {type(last_error).__name__}")

    async def degraded_response(self, parameters: dict[str, JsonValue]) -> dict[str, JsonValue]:
        del parameters
        if self.config.fallback == "fail":
            raise ConnectorError("Connector is degraded")
        return {"status": "degraded", "source": "fallback"}

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()


__all__ = [
    "BaseHttpConnector", "ConnectorConfig", "ConnectorError", "ConnectorRateLimitError", "TokenBucket",
]

