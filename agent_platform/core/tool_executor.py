"""Validated, cancellable, retry-bounded, idempotent tool execution."""

import asyncio
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from agent_platform.core.errors import ToolExecutionError, ToolTimeoutError
from agent_platform.core.schema_validator import SchemaValidator
from agent_platform.core.tool_registry import ToolRegistry
from agent_platform.models import ToolCall, ToolContext, ToolReceipt


@dataclass(frozen=True)
class _CachedReceipt:
    expires_at: float
    receipt: ToolReceipt


class ToolExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        *,
        idempotency_ttl_seconds: int = 3600,
        mutation_idempotency_ttl_seconds: int = 120,
    ) -> None:
        self._registry = registry
        self._ttl = idempotency_ttl_seconds
        # Keys prefixed with "mutation:" come from tools that change local
        # state.  A short window still absorbs double-click storms while not
        # swallowing a user's repeated "remind me again in 30 minutes" intent
        # an hour later.
        self._mutation_ttl = mutation_idempotency_ttl_seconds
        self._cache: dict[str, _CachedReceipt] = {}
        self._cache_lock = asyncio.Lock()

    async def execute(
        self,
        call: ToolCall,
        cancellation: asyncio.Event | None = None,
        context: ToolContext | None = None,
    ) -> ToolReceipt:
        tool = self._registry.get(call.tool_name)
        SchemaValidator.validate(call.arguments, tool.metadata.parameters_schema)
        key = call.idempotency_key or tool.idempotency_key(call.arguments)
        if context is not None:
            # Identical arguments from two accounts are different operations;
            # the cache key must never cross owner boundaries.
            key = f"owner:{context.owner}:{key}"
        cached = await self._get_cached(key)
        if cached is not None:
            return cached
        if cancellation is not None and cancellation.is_set():
            raise asyncio.CancelledError("Task was cancelled before tool execution")

        last_error: Exception | None = None
        for attempt in range(tool.metadata.retry_budget + 1):
            try:
                receipt = await self._execute_once(tool, call, cancellation, context)
                if receipt.tool_name != call.tool_name:
                    raise ToolExecutionError("Tool receipt name does not match registration")
                if receipt.success:
                    await self._store_cached(key, receipt)
                return receipt
            except ToolTimeoutError as exc:
                last_error = exc
                if attempt >= tool.metadata.retry_budget:
                    raise
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                last_error = exc
                if attempt >= tool.metadata.retry_budget:
                    if isinstance(exc, ToolExecutionError):
                        raise
                    raise ToolExecutionError(f"Tool {call.tool_name} failed: {type(exc).__name__}") from exc
        raise ToolExecutionError(f"Tool failed: {last_error}")

    async def _execute_once(
        self,
        tool: object,
        call: ToolCall,
        cancellation: asyncio.Event | None,
        context: ToolContext | None,
    ) -> ToolReceipt:
        started = time.perf_counter()
        execution = asyncio.create_task(tool.execute(call.arguments, context))  # type: ignore[attr-defined]
        waiters: set[asyncio.Task[object]] = {execution}
        cancel_waiter: asyncio.Task[object] | None = None
        if cancellation is not None:
            cancel_waiter = asyncio.create_task(cancellation.wait())
            waiters.add(cancel_waiter)
        done, pending = await asyncio.wait(waiters, timeout=tool.metadata.timeout_seconds, return_when=asyncio.FIRST_COMPLETED)  # type: ignore[attr-defined]
        for pending_task in pending:
            pending_task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        if not done:
            execution.cancel()
            raise ToolTimeoutError(f"Tool {call.tool_name} exceeded {tool.metadata.timeout_seconds}s")
        if cancel_waiter is not None and cancel_waiter in done and cancellation and cancellation.is_set():
            execution.cancel()
            await asyncio.gather(execution, return_exceptions=True)
            raise asyncio.CancelledError("Task cancelled during tool execution")
        receipt = await execution
        duration = (time.perf_counter() - started) * 1000
        return receipt.model_copy(update={"duration_ms": duration, "started_at": datetime.now(UTC)})

    async def _get_cached(self, key: str) -> ToolReceipt | None:
        now = time.monotonic()
        async with self._cache_lock:
            expired = [item_key for item_key, item in self._cache.items() if item.expires_at <= now]
            for item_key in expired:
                self._cache.pop(item_key, None)
            item = self._cache.get(key)
            return item.receipt if item else None

    async def _store_cached(self, key: str, receipt: ToolReceipt) -> None:
        ttl = self._mutation_ttl if key.startswith("mutation:") else self._ttl
        async with self._cache_lock:
            self._cache[key] = _CachedReceipt(time.monotonic() + ttl, receipt)


__all__ = ["ToolExecutor"]
