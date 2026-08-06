"""Abstract contracts implemented by all platform modules."""

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path

from pydantic import JsonValue

from agent_platform.models import (
    ClassificationResult,
    ModelMessage,
    PolicyContext,
    PolicyDecision,
    ResourceMetrics,
    RoutingDecision,
    RoutingRequest,
    TaskRecord,
    ToolMetadata,
    ToolReceipt,
)


class ModelAdapter(ABC):
    """Generate schema-constrained JSON without exposing provider details."""

    @abstractmethod
    async def generate(
        self,
        messages: Sequence[ModelMessage],
        response_schema: dict[str, JsonValue],
        max_tokens: int = 512,
    ) -> dict[str, JsonValue]:
        """Return a JSON object conforming to ``response_schema``."""

    @abstractmethod
    async def close(self) -> None:
        """Release provider connections; repeated calls must be safe."""


class Tool(ABC):
    """A deterministic, schema-described action managed by ToolExecutor."""

    @property
    @abstractmethod
    def metadata(self) -> ToolMetadata:
        """Return immutable registration metadata."""

    @abstractmethod
    def idempotency_key(self, arguments: dict[str, JsonValue]) -> str:
        """Return a stable key for semantically equivalent arguments."""

    @abstractmethod
    async def execute(self, arguments: dict[str, JsonValue]) -> ToolReceipt:
        """Execute with already validated arguments and return a receipt."""


class Policy(ABC):
    """Authorize an action and describe any required user confirmation."""

    @abstractmethod
    def evaluate(self, context: PolicyContext) -> PolicyDecision:
        """Return a deterministic authorization decision."""


class DataClassifier(ABC):
    """Classify and redact text before model, log, queue, or cloud use."""

    @abstractmethod
    def classify(self, text: str) -> ClassificationResult:
        """Return the highest data class and redacted representation."""

    @abstractmethod
    def check_outbound(self, text: str) -> ClassificationResult:
        """Validate whether text may leave the device or raise an error."""


class Router(ABC):
    """Choose local, cloud, queued, or rejected execution."""

    @abstractmethod
    def decide(self, request: RoutingRequest, metrics: ResourceMetrics) -> RoutingDecision:
        """Apply routing factors in documented priority order."""


class TaskStore(ABC):
    """Persist task state with optimistic concurrency control."""

    @abstractmethod
    async def create(self, task: TaskRecord) -> TaskRecord:
        """Persist a newly received task."""

    @abstractmethod
    async def get(self, task_id: str) -> TaskRecord:
        """Load one task or raise TaskNotFoundError."""

    @abstractmethod
    async def update(self, task: TaskRecord, expected_version: int) -> TaskRecord:
        """Update only when ``expected_version`` matches stored state."""

    @abstractmethod
    async def recover_incomplete(self) -> list[TaskRecord]:
        """Load all non-terminal tasks after restart."""


class Embedder(ABC):
    """Map text to a deterministic numeric vector."""

    @abstractmethod
    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch without changing input order."""


class FileOpener(ABC):
    """Platform abstraction for opening a file with its default app."""

    @abstractmethod
    async def open(self, path: Path) -> dict[str, JsonValue]:
        """Open an authorized path and return a real platform receipt."""


NotificationCallback = Callable[[dict[str, JsonValue]], Awaitable[None]]

__all__ = [
    "DataClassifier", "Embedder", "FileOpener", "ModelAdapter", "NotificationCallback", "Policy",
    "Router", "TaskStore", "Tool",
]

