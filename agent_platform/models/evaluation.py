"""Model-independent evaluation dataset and report contracts."""

from typing import Literal

from pydantic import Field, JsonValue

from agent_platform.models.common import StrictModel


class EvaluationCase(StrictModel):
    id: str = Field(..., min_length=1, description="Stable case identifier")
    input_text: str = Field(..., min_length=1, description="Synthetic request text")
    expected_intent: str = Field(..., description="Expected intent")
    expected_arguments: dict[str, JsonValue] = Field(default_factory=dict, description="Expected argument subset")
    expected_tool: str = Field(..., description="Expected tool name")
    tolerance: dict[str, JsonValue] = Field(default_factory=dict, description="Allowed comparison tolerances")
    aliases: dict[str, list[JsonValue]] = Field(
        default_factory=dict,
        description="Pre-registered field-level semantic aliases for detailed evaluation",
    )
    expected_pipeline_outcome: str | None = Field(
        default=None,
        description="Optional dry-run expectation such as executed or awaiting_confirmation",
    )


class EvaluationMetrics(StrictModel):
    total: int = Field(default=0, ge=0, description="Number of cases")
    intent_accuracy: float = Field(default=0.0, ge=0, le=1, description="Intent accuracy")
    argument_accuracy: float = Field(default=0.0, ge=0, le=1, description="Argument accuracy")
    tool_accuracy: float = Field(default=0.0, ge=0, le=1, description="Tool selection accuracy")
    schema_compliance: float = Field(default=0.0, ge=0, le=1, description="Schema compliance")
    latency_p50_ms: float = Field(default=0, ge=0, description="Median latency")
    latency_p95_ms: float = Field(default=0, ge=0, description="95th percentile latency")
    latency_p99_ms: float = Field(default=0, ge=0, description="99th percentile latency")


class RawEvaluationSnapshot(StrictModel):
    """One replayable model response, stored as one JSONL object per evaluation case."""

    case_id: str = Field(..., min_length=1)
    input_hash: str = Field(..., min_length=1)
    provider: str = Field(default="unknown", min_length=1)
    model: str = Field(default="unknown", min_length=1)
    model_digest: str = Field(default="unknown", min_length=1)
    prompt_version: str = Field(default="unknown", min_length=1)
    dataset_digest: str = Field(default="unknown", min_length=1)
    route_source: str = Field(default="unknown", min_length=1)
    model_calls: int = Field(default=0, ge=0)
    schema_repaired: bool = False
    raw_result: dict[str, JsonValue] | None = None
    model_error: str | None = None
    model_schema_invalid: bool = False
    latency_ms: float = Field(default=0.0, ge=0)


class DetailedEvaluationMetrics(StrictModel):
    """Detailed metrics kept separate from the legacy evaluation metric contract."""

    total: int = Field(default=0, ge=0)
    raw_intent_accuracy: float = Field(default=0.0, ge=0, le=1)
    raw_tool_accuracy: float = Field(default=0.0, ge=0, le=1)
    raw_contract_accuracy: float = Field(default=0.0, ge=0, le=1)
    raw_exact_argument_accuracy: float = Field(default=0.0, ge=0, le=1)
    normalized_contract_accuracy: float = Field(default=0.0, ge=0, le=1)
    semantic_match_rate: float = Field(default=0.0, ge=0, le=1)
    semantic_adjudicated_accuracy: float = Field(default=0.0, ge=0, le=1)
    semantic_coverage: float = Field(default=0.0, ge=0, le=1)
    needs_review_count: int = Field(default=0, ge=0)
    model_schema_invalid_count: int = Field(default=0, ge=0)
    end_to_end_accuracy: float = Field(default=0.0, ge=0, le=1)


class DetailedCaseResult(StrictModel):
    """Inspectable outcome for one case across raw, normalized, and dry-run layers."""

    id: str = Field(..., min_length=1)
    raw_result: dict[str, JsonValue] | None = None
    model_error: str | None = None
    model_schema_invalid: bool = False
    latency_ms: float = Field(default=0.0, ge=0)
    route_source: str = "unknown"
    model_calls: int = Field(default=0, ge=0)
    schema_repaired: bool = False
    raw_intent_ok: bool = False
    raw_tool_ok: bool = False
    raw_contract_ok: bool = False
    raw_exact_arguments_ok: bool = False
    normalized_arguments: dict[str, JsonValue] | None = None
    normalization_rules: list[str] = Field(default_factory=list)
    normalized_contract_ok: bool = False
    semantic_status: Literal["match", "mismatch", "needs_review"] = "needs_review"
    semantic_reason: str = "not_scored"
    pipeline_outcome: str = "unavailable"
    pipeline_outcome_ok: bool = False
    pipeline_detail: str | None = None
    end_to_end_ok: bool = False


class DetailedEvaluationReport(StrictModel):
    metrics: DetailedEvaluationMetrics = Field(default_factory=DetailedEvaluationMetrics)
    cases: list[DetailedCaseResult] = Field(default_factory=list)


class EvaluationRunMetadata(StrictModel):
    provider: str = "unknown"
    model: str = "unknown"
    model_digest: str = "unknown"
    prompt_version: str = "unknown"
    dataset_digest: str = "unknown"
    baseline_report_digest: str = "unknown"
    baseline_snapshot_digest: str = "unknown"


class EvaluationReport(StrictModel):
    metrics: EvaluationMetrics = Field(..., description="Aggregate metrics")
    per_intent: dict[str, float] = Field(default_factory=dict, description="Accuracy by intent")
    failures: list[dict[str, JsonValue]] = Field(default_factory=list, description="Sanitized failure details")
    previous_diff: dict[str, float] = Field(default_factory=dict, description="Metric changes from prior run")
    detailed: DetailedEvaluationReport | None = None
    run_metadata: EvaluationRunMetadata | None = None

__all__ = [
    "DetailedCaseResult",
    "DetailedEvaluationMetrics",
    "DetailedEvaluationReport",
    "EvaluationCase",
    "EvaluationMetrics",
    "EvaluationReport",
    "EvaluationRunMetadata",
    "RawEvaluationSnapshot",
]
