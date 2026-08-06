"""Unified exception hierarchy."""


class AgentPlatformError(Exception):
    code = "agent_platform_error"
    retryable = False

    def __init__(self, detail: str, *, retryable: bool | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        if retryable is not None:
            self.retryable = retryable


class ConfigurationError(AgentPlatformError):
    code = "configuration_error"


class ModelError(AgentPlatformError):
    code = "model_error"


class ModelSchemaError(ModelError):
    """A complete JSON object failed the requested response schema."""

    code = "model_schema_error"

    def __init__(self, detail: str, *, raw_result: dict[str, object], validation_errors: tuple[str, ...]) -> None:
        super().__init__(detail)
        self.raw_result = raw_result
        self.validation_errors = validation_errors


class ModelTimeoutError(ModelError):
    code = "model_timeout"
    retryable = True


class ModelRateLimitError(ModelError):
    code = "model_rate_limited"
    retryable = True


class ModelBusyError(ModelError):
    code = "model_busy"
    retryable = True


class TaskNotFoundError(AgentPlatformError):
    code = "task_not_found"


class InvalidTransitionError(AgentPlatformError):
    code = "invalid_task_transition"


class ConcurrencyConflictError(AgentPlatformError):
    code = "concurrency_conflict"
    retryable = True


class SchemaValidationError(AgentPlatformError):
    code = "schema_validation_error"


class ToolNotFoundError(AgentPlatformError):
    code = "tool_not_found"


class ToolExecutionError(AgentPlatformError):
    code = "tool_execution_error"


class ToolTimeoutError(ToolExecutionError):
    code = "tool_timeout"
    retryable = True


class PermissionDeniedError(AgentPlatformError):
    code = "permission_denied"


class SensitiveDataError(PermissionDeniedError):
    code = "sensitive_data_blocked"


class DatabaseInUseError(AgentPlatformError):
    code = "database_in_use"


__all__ = [
    "AgentPlatformError", "ConcurrencyConflictError", "ConfigurationError", "DatabaseInUseError",
    "InvalidTransitionError", "ModelBusyError", "ModelError", "ModelRateLimitError", "ModelSchemaError", "ModelTimeoutError",
    "PermissionDeniedError", "SchemaValidationError", "SensitiveDataError", "TaskNotFoundError",
    "ToolExecutionError", "ToolNotFoundError", "ToolTimeoutError",
]
