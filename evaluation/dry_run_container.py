"""Isolated AgentCore execution for side-effect-free detailed evaluation."""

from __future__ import annotations

import hashlib
import json
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pydantic import JsonValue

from agent_platform.core.agent_core import AgentCore
from agent_platform.core.audit_service import AuditService
from agent_platform.core.data_classification import DataClassificationService
from agent_platform.core.edge_cloud_router import EdgeCloudRouter
from agent_platform.core.model_gateway import ModelGateway
from agent_platform.core.policy_engine import PolicyEngine
from agent_platform.core.resource_monitor import ResourceMonitor
from agent_platform.core.session_manager import SessionManager
from agent_platform.core.task_api import TaskAPI
from agent_platform.core.tool_executor import ToolExecutor
from agent_platform.core.tool_registry import ToolRegistry
from agent_platform.models import (
    ModelMessage,
    TaskCreate,
    TaskState,
    ToolMetadata,
    ToolReceipt,
    is_argument_extraction_schema,
    is_intent_classification_schema,
)
from agent_platform.models.evaluation import EvaluationCase


@dataclass(frozen=True)
class DryRunResult:
    outcome: str
    detail: str | None = None


class DryRunContainer(Protocol):
    async def evaluate(
        self,
        *,
        case: EvaluationCase,
        intent: str,
        arguments: dict[str, JsonValue],
        raw_result: dict[str, JsonValue],
    ) -> DryRunResult: ...

    async def close(self) -> None: ...


class ReplayModelAdapter:
    """One-response adapter used only inside a temporary dry-run container."""

    def __init__(self) -> None:
        self._raw_result: dict[str, JsonValue] | None = None

    def set_response(self, raw_result: Mapping[str, JsonValue]) -> None:
        self._raw_result = dict(raw_result)

    async def generate(
        self,
        messages: Sequence[ModelMessage],
        response_schema: dict[str, JsonValue],
        max_tokens: int = 512,
    ) -> dict[str, JsonValue]:
        del messages, max_tokens
        if self._raw_result is None:
            raise RuntimeError("No raw snapshot response configured for dry-run")
        if is_intent_classification_schema(response_schema):
            return {
                "intent": self._raw_result["intent"],
                "confidence": self._raw_result.get("confidence", 1.0),
            }
        if is_argument_extraction_schema(response_schema):
            return {
                "arguments": dict(self._raw_result.get("arguments", {})),
                "missing_fields": list(self._raw_result.get("missing_fields", [])),
            }
        return dict(self._raw_result)

    async def close(self) -> None:
        return None


class DryRunTool:
    """Metadata-preserving tool wrapper that never delegates to a production tool."""

    def __init__(self, metadata: ToolMetadata, executions: list[str]) -> None:
        self._metadata = metadata
        self._executions = executions

    @property
    def metadata(self) -> ToolMetadata:
        return self._metadata

    def idempotency_key(self, arguments: dict[str, JsonValue]) -> str:
        encoded = json.dumps(arguments, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return f"dry-run:{self.metadata.name}:{hashlib.sha256(encoded).hexdigest()}"

    async def execute(self, arguments: dict[str, JsonValue]) -> ToolReceipt:
        self._executions.append(self.metadata.name)
        return ToolReceipt(
            tool_name=self.metadata.name,
            actual_arguments=dict(arguments),
            success=True,
            output_summary=f"Dry-run simulated {self.metadata.name}",
            output={"dry_run": True, "tool": self.metadata.name},
        )


class EvaluationDryRunContainer:
    """Temporary full pipeline using replayed model output and inert tool wrappers.

    The container owns an isolated SQLite task store and audit directory. Its
    registry is populated only from production metadata, so schema, policy,
    router, and confirmation behavior remain representative while tool calls
    cannot affect any user file, reminder, or external integration.
    """

    def __init__(self, production_registry: Any) -> None:
        self._tempdir = tempfile.TemporaryDirectory(prefix="agent-platform-evaluation-")
        root = Path(self._tempdir.name)
        self._classifier = DataClassificationService()
        self._store = SessionManager(root / "tasks.db")
        self._tasks = TaskAPI(self._store)
        self._audit = AuditService(root / "audit", self._classifier, flush_size=1)
        self._replay_adapter = ReplayModelAdapter()
        self._gateway = ModelGateway(self._replay_adapter)
        registry = ToolRegistry()
        self.executed_tools: list[str] = []
        for name in production_registry.names():
            registry.register(DryRunTool(production_registry.get(name).metadata, self.executed_tools))
        registry.freeze()
        self._registry = registry
        self._agent = AgentCore(
            tasks=self._tasks,
            gateway=self._gateway,
            registry=registry,
            executor=ToolExecutor(registry),
            classifier=self._classifier,
            policy=PolicyEngine(),
            router=EdgeCloudRouter(self._classifier),
            resources=ResourceMonitor("normal"),
            audit=self._audit,
            network_available=False,
        )
        self._initialized = False
        self._closed = False

    async def _initialize(self) -> None:
        if not self._initialized:
            await self._tasks.initialize()
            self._initialized = True

    async def evaluate(
        self,
        *,
        case: EvaluationCase,
        intent: str,
        arguments: dict[str, JsonValue],
        raw_result: dict[str, JsonValue],
    ) -> DryRunResult:
        del intent, arguments
        if self._closed:
            raise RuntimeError("Dry-run container is closed")
        await self._initialize()
        self._replay_adapter.set_response(raw_result)
        task = await self._agent.submit(TaskCreate(text=case.input_text, session_id="evaluation-dry-run"))
        if task.state == TaskState.COMPLETED:
            return DryRunResult("executed")
        if task.state == TaskState.AWAITING_CONFIRMATION:
            result_type = str((task.result or {}).get("type", "confirmation"))
            if result_type == "risk_confirmation":
                return DryRunResult("awaiting_confirmation", "High-risk confirmation was required; tool was not executed")
            if result_type == "missing_fields":
                return DryRunResult("awaiting_missing_fields", "Required fields were not supplied; tool was not executed")
            return DryRunResult("awaiting_confirmation", f"Confirmation required: {result_type}")
        if task.state == TaskState.WAITING_NETWORK:
            return DryRunResult("waiting_network")
        if task.state == TaskState.FAILED:
            return DryRunResult("failed", task.error)
        return DryRunResult(task.state.value, task.error)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._audit.flush()
        await self._gateway.close()
        await self._store.close()
        self._tempdir.cleanup()


class UnavailableDryRunContainer:
    """No-side-effect fallback when detailed evaluation has no tool registry."""

    async def evaluate(
        self,
        *,
        case: EvaluationCase,
        intent: str,
        arguments: dict[str, JsonValue],
        raw_result: dict[str, JsonValue],
    ) -> DryRunResult:
        del case, intent, arguments, raw_result
        return DryRunResult("unavailable", "No registered tool metadata was supplied for dry-run")

    async def close(self) -> None:
        return None


def outcome_matches(expected: str | None, result: DryRunResult) -> bool:
    """Only explicit case expectations count as end-to-end success."""

    return expected is not None and result.outcome == expected


__all__ = [
    "DryRunContainer",
    "DryRunResult",
    "DryRunTool",
    "EvaluationDryRunContainer",
    "ReplayModelAdapter",
    "UnavailableDryRunContainer",
    "outcome_matches",
]
