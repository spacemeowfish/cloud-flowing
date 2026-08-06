"""Data-classification and authorization contracts."""

from pydantic import Field, JsonValue

from agent_platform.models.common import DataLevel, RiskLevel, StrictModel


class DataFinding(StrictModel):
    level: DataLevel = Field(..., description="Detected data class")
    kind: str = Field(..., description="Matched rule name")
    start: int = Field(..., ge=0, description="Start character offset")
    end: int = Field(..., ge=0, description="End character offset")
    replacement: str = Field(..., description="Safe replacement label")


class ClassificationResult(StrictModel):
    level: DataLevel = Field(default=DataLevel.D0, description="Highest detected class")
    findings: list[DataFinding] = Field(default_factory=list, description="All non-overlapping findings")
    redacted_text: str = Field(..., description="Text with sensitive values removed")


class PolicyContext(StrictModel):
    role: str = Field(..., description="Authenticated role")
    data_domain: str = Field(..., description="Requested data domain")
    risk_level: RiskLevel = Field(..., description="Operation risk")
    data_level: DataLevel = Field(..., description="Highest input data class")
    action: str = Field(..., description="Requested action")
    arguments: dict[str, JsonValue] = Field(default_factory=dict, description="Validated action arguments")


class ConfirmationRequest(StrictModel):
    title: str = Field(..., description="Confirmation title")
    target: str = Field(..., description="Affected object")
    content: str = Field(..., description="Action summary")
    amount: str | None = Field(default=None, description="Monetary amount when applicable")
    impact: str = Field(..., description="Expected effect")
    reversible: bool = Field(default=False, description="Whether the action can be undone")


class PolicyDecision(StrictModel):
    allowed: bool = Field(..., description="Whether the action may proceed")
    reason: str = Field(..., description="Stable decision explanation")
    requires_confirmation: bool = Field(default=False, description="Whether user confirmation is required")
    confirmation: ConfirmationRequest | None = Field(default=None, description="UI-neutral confirmation payload")

__all__ = [
    "ClassificationResult",
    "ConfirmationRequest",
    "DataFinding",
    "PolicyContext",
    "PolicyDecision",
]
