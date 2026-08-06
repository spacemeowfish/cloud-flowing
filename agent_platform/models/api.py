"""HTTP-specific protocol models."""

from pydantic import Field

from agent_platform.models.common import StrictModel


class ErrorResponse(StrictModel):
    code: str = Field(..., description="Stable machine-readable code")
    message: str = Field(..., description="Safe user-facing message")
    retryable: bool = Field(default=False, description="Whether retry may succeed")
    detail: str | None = Field(default=None, description="Optional diagnostic detail")

__all__ = ["ErrorResponse"]

