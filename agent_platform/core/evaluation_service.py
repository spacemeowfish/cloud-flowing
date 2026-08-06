"""Model-independent fixed-dataset evaluation and replayable detailed scoring."""

from __future__ import annotations

import asyncio
import hashlib
import json
import statistics
import time
from collections import defaultdict
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import JsonValue, ValidationError as PydanticValidationError

from agent_platform.core.errors import ModelError, ModelSchemaError
from agent_platform.core.model_gateway import ModelGateway
from agent_platform.core.data_classification import DataClassificationService
from agent_platform.models import (
    INTENT_RESPONSE_SCHEMA,
    EvaluationCase,
    EvaluationMetrics,
    EvaluationReport,
    EvaluationRunMetadata,
    IntentResult,
    MessageRole,
    ModelMessage,
    build_model_acceptance_schema,
    is_model_acceptance_schema,
)
from agent_platform.models.evaluation import (
    DetailedCaseResult,
    DetailedEvaluationMetrics,
    DetailedEvaluationReport,
    RawEvaluationSnapshot,
)
from evaluation.contract_check import check_contract
from evaluation.dry_run_container import (
    DryRunContainer,
    EvaluationDryRunContainer,
    UnavailableDryRunContainer,
    outcome_matches,
)
from evaluation.semantic_match import match_arguments


ArgumentNormalizer = Callable[..., object]


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return ordered[index]


def _input_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _dataset_digest(cases: list[EvaluationCase]) -> str:
    payload = [case.model_dump(mode="json") for case in cases]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _error_summary(error: Exception) -> str:
    message = " ".join(str(error).split())
    return f"{type(error).__name__}: {message[:400]}"


def _is_schema_error(error: Exception) -> bool:
    """Classify adapter-side schema rejection without treating transport failures as schema failures."""

    if isinstance(error, (JsonSchemaValidationError, PydanticValidationError, ModelSchemaError)):
        return True
    # CloudModelAdapter owns JSON parsing and schema validation, so it exposes
    # both failures through its public ModelError boundary.
    return isinstance(error, ModelError) and error.detail == "Cloud model returned invalid structured JSON"


def _snapshot_has_schema_error(snapshot: RawEvaluationSnapshot) -> bool:
    """Keep historical raw snapshots correctly classified after a scorer upgrade."""

    return snapshot.model_schema_invalid or snapshot.model_error == "ModelError: Cloud model returned invalid structured JSON"


class EvaluationService:
    """Score raw model output, or replay a frozen snapshot without calling a model."""

    def __init__(
        self,
        gateway: ModelGateway,
        *,
        registry: Any | None = None,
        normalizer: ArgumentNormalizer | None = None,
        dry_run_container: DryRunContainer | None = None,
        response_schema: dict[str, JsonValue] | None = None,
    ) -> None:
        self._gateway = gateway
        self._classifier = DataClassificationService()
        self._registry = registry
        self._normalizer = normalizer
        self._dry_run_container: DryRunContainer = dry_run_container or (
            EvaluationDryRunContainer(registry) if registry is not None else UnavailableDryRunContainer()
        )
        self._response_schema = response_schema or (
            build_model_acceptance_schema(registry) if registry is not None else INTENT_RESPONSE_SCHEMA
        )
        self._cache: dict[Path, tuple[float, list[EvaluationCase]]] = {}

    def load_cases(self, directory: Path) -> list[EvaluationCase]:
        cases: list[EvaluationCase] = []
        for path in sorted(directory.glob("*.json")):
            mtime = path.stat().st_mtime
            cached = self._cache.get(path)
            if cached and cached[0] == mtime:
                file_cases = cached[1]
            else:
                payload = json.loads(path.read_text(encoding="utf-8"))
                file_cases = [EvaluationCase.model_validate(item) for item in payload]
                self._cache[path] = (mtime, file_cases)
            cases.extend(file_cases)
        return cases

    @staticmethod
    def load_raw_snapshots(path: Path) -> dict[str, RawEvaluationSnapshot]:
        """Load a JSONL snapshot and reject duplicate case IDs deterministically."""

        snapshots: dict[str, RawEvaluationSnapshot] = {}
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                snapshot = RawEvaluationSnapshot.model_validate_json(line)
            except Exception as exc:  # Snapshot corruption must not silently alter scores.
                raise ValueError(f"Invalid raw snapshot line {line_number}: {_error_summary(exc)}") from exc
            if snapshot.case_id in snapshots:
                raise ValueError(f"Duplicate raw snapshot case_id: {snapshot.case_id}")
            snapshots[snapshot.case_id] = snapshot
        return snapshots

    @staticmethod
    def validate_snapshot_inputs(
        cases: list[EvaluationCase], snapshots: Mapping[str, RawEvaluationSnapshot]
    ) -> None:
        """Require a baseline snapshot to represent exactly the current fixed inputs."""

        expected = {case.id: _input_hash(case.input_text) for case in cases}
        if set(snapshots) != set(expected):
            missing = sorted(set(expected) - set(snapshots))
            extra = sorted(set(snapshots) - set(expected))
            raise ValueError(f"Baseline snapshot case IDs differ; missing={missing}; extra={extra}")
        mismatched = sorted(case_id for case_id, digest in expected.items() if snapshots[case_id].input_hash != digest)
        if mismatched:
            raise ValueError(f"Baseline snapshot input hashes differ: {mismatched}")

    @staticmethod
    def write_raw_snapshots(snapshots: list[RawEvaluationSnapshot], path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        content = "\n".join(item.model_dump_json(exclude_none=True) for item in snapshots)
        path.write_text(f"{content}\n" if content else "", encoding="utf-8")

    def _tool_schemas(self) -> dict[str, Mapping[str, JsonValue]]:
        if self._registry is None:
            return {}
        schemas: dict[str, Mapping[str, JsonValue]] = {}
        for name in self._registry.names():
            schemas[name] = self._registry.get(name).metadata.parameters_schema
        return schemas

    async def close(self) -> None:
        """Release the temporary dry-run resources owned by this evaluation service."""

        await self._dry_run_container.close()

    async def _capture_one(
        self,
        case: EvaluationCase,
        *,
        metadata: Mapping[str, str],
    ) -> RawEvaluationSnapshot:
        started = time.perf_counter()
        raw: dict[str, JsonValue] | None = None
        model_error: str | None = None
        model_schema_invalid = False
        route_source = "legacy_one_shot"
        model_calls = 1
        schema_repaired = False
        try:
            if is_model_acceptance_schema(self._response_schema):
                interpretation = await self._gateway.interpret(case.input_text, self._response_schema)
                generated = interpretation.intent.model_dump(mode="json")
                route_source = interpretation.route_source
                model_calls = interpretation.model_calls
                schema_repaired = interpretation.schema_repaired
            else:
                generated = await self._gateway.generate(
                    [ModelMessage(role=MessageRole.USER, content=case.input_text)], self._response_schema
                )
            if isinstance(generated, dict):
                raw = generated
                errors = list(Draft202012Validator(self._response_schema).iter_errors(raw))
                if errors:
                    model_error = "ModelSchemaInvalid: " + "; ".join(error.message for error in errors)
                    model_schema_invalid = True
            else:
                model_error = f"ModelResponseTypeError: expected object, got {type(generated).__name__}"
        except Exception as exc:
            if isinstance(exc, ModelSchemaError):
                raw = dict(exc.raw_result)
            model_error = _error_summary(exc)
            model_schema_invalid = _is_schema_error(exc)
        return RawEvaluationSnapshot(
            case_id=case.id,
            input_hash=_input_hash(case.input_text),
            provider=metadata.get("provider", "unknown"),
            model=metadata.get("model", "unknown"),
            model_digest=metadata.get("model_digest", "unknown"),
            prompt_version=metadata.get("prompt_version", "unknown"),
            dataset_digest=metadata.get("dataset_digest", "unknown"),
            route_source=route_source,
            model_calls=model_calls,
            schema_repaired=schema_repaired,
            raw_result=raw,
            model_error=model_error,
            model_schema_invalid=model_schema_invalid,
            latency_ms=(time.perf_counter() - started) * 1000,
        )

    def _parse_snapshot(self, snapshot: RawEvaluationSnapshot) -> tuple[IntentResult | None, bool, str | None]:
        if snapshot.model_error:
            return None, False, snapshot.model_error
        if snapshot.raw_result is None:
            return None, False, "Model returned no structured result"
        errors = list(Draft202012Validator(self._response_schema).iter_errors(snapshot.raw_result))
        if errors:
            return None, False, "; ".join(error.message for error in errors)
        try:
            return IntentResult.model_validate(snapshot.raw_result), True, None
        except Exception as exc:
            return None, False, _error_summary(exc)

    def _normalize(
        self,
        *,
        intent: str,
        arguments: dict[str, JsonValue],
        request_text: str,
    ) -> tuple[dict[str, JsonValue], list[str], str | None]:
        if self._normalizer is None:
            return dict(arguments), [], None
        try:
            result = self._normalizer(intent=intent, arguments=dict(arguments), request_text=request_text)
            normalized = getattr(result, "arguments", result)
            applied_rules = getattr(result, "applied_rules", [])
            if not isinstance(normalized, dict):
                return {}, [], "Normalizer returned non-object arguments"
            if not isinstance(applied_rules, list) or not all(isinstance(item, str) for item in applied_rules):
                return {}, [], "Normalizer returned invalid applied_rules"
            return dict(normalized), list(applied_rules), None
        except Exception as exc:
            return {}, [], _error_summary(exc)

    def _redact_report_arguments(self, arguments: dict[str, JsonValue] | None) -> dict[str, JsonValue] | None:
        """Keep replay snapshots raw, but redact values emitted in human-readable reports."""

        if arguments is None:
            return None
        serialized = json.dumps(arguments, ensure_ascii=False, sort_keys=True)
        redacted = self._classifier.classify(serialized).redacted_text
        try:
            parsed = json.loads(redacted)
        except json.JSONDecodeError:
            return {"redacted": "[REDACTED:UNPARSEABLE_ARGUMENTS]"}
        return parsed if isinstance(parsed, dict) else {"redacted": "[REDACTED:INVALID_ARGUMENTS]"}

    async def run(
        self,
        cases: list[EvaluationCase],
        previous: EvaluationReport | None = None,
        rate_limit_per_second: float | None = None,
        *,
        detailed: bool = False,
        raw_snapshots: Mapping[str, RawEvaluationSnapshot] | None = None,
        capture_raw: Path | None = None,
        snapshot_metadata: Mapping[str, str] | None = None,
    ) -> EvaluationReport:
        """Run legacy scoring, with optional raw replay and detailed scoring layers.

        `raw_snapshots` avoids a fresh model call.  `capture_raw` records every
        case, including malformed responses and gateway failures, as JSONL.
        """

        if raw_snapshots is not None and capture_raw is not None:
            raise ValueError("raw_snapshots and capture_raw cannot be used together")
        metadata = dict(snapshot_metadata or {})
        metadata["dataset_digest"] = _dataset_digest(cases)
        intent_hits = argument_hits = tool_hits = schema_hits = 0
        latencies: list[float] = []
        by_intent: dict[str, list[bool]] = defaultdict(list)
        failures: list[dict[str, JsonValue]] = []
        snapshots: list[RawEvaluationSnapshot] = []
        detailed_cases: list[DetailedCaseResult] = []
        schemas = self._tool_schemas()
        previous_started = 0.0

        for case in cases:
            if raw_snapshots is None:
                if rate_limit_per_second and previous_started:
                    minimum_interval = 1.0 / rate_limit_per_second
                    remaining = minimum_interval - (time.perf_counter() - previous_started)
                    if remaining > 0:
                        await asyncio.sleep(remaining)
                previous_started = time.perf_counter()
                snapshot = await self._capture_one(case, metadata=metadata)
            else:
                snapshot = raw_snapshots.get(case.id)
                if snapshot is None:
                    snapshot = RawEvaluationSnapshot(
                        case_id=case.id,
                        input_hash=_input_hash(case.input_text),
                        model_error="SnapshotMissingError: no entry for this case",
                    )
                elif snapshot.input_hash != _input_hash(case.input_text):
                    snapshot = snapshot.model_copy(
                        update={"raw_result": None, "model_error": "SnapshotInputHashMismatchError: input does not match case"}
                    )
            snapshots.append(snapshot)
            latencies.append(snapshot.latency_ms)
            result, schema_ok, parse_error = self._parse_snapshot(snapshot)
            schema_hits += int(schema_ok)

            if result is None:
                intent_ok = tool_ok = arguments_ok = False
                actual_intent: str | None = None
            else:
                intent_ok = result.intent == case.expected_intent
                tool_ok = result.intent == case.expected_tool
                arguments_ok = all(result.arguments.get(key) == value for key, value in case.expected_arguments.items())
                actual_intent = result.intent
            intent_hits += int(intent_ok)
            tool_hits += int(tool_ok)
            argument_hits += int(arguments_ok)
            by_intent[case.expected_intent].append(intent_ok and tool_ok)

            if not (intent_ok and tool_ok and arguments_ok and schema_ok):
                failed_dimensions = [
                    name
                    for name, passed in (
                        ("intent", intent_ok),
                        ("arguments", arguments_ok),
                        ("tool", tool_ok),
                        ("schema", schema_ok),
                    )
                    if not passed
                ]
                failure: dict[str, JsonValue] = {
                    "id": case.id,
                    "expected_intent": case.expected_intent,
                    "failed_dimensions": failed_dimensions,
                }
                if actual_intent is not None:
                    failure["actual_intent"] = actual_intent
                if parse_error:
                    failure["model_error"] = parse_error
                failures.append(failure)

            if detailed:
                detailed_cases.append(
                    await self._score_detailed_case(
                        case=case,
                        snapshot=snapshot,
                        result=result,
                        schema_ok=schema_ok,
                        parse_error=parse_error,
                        schemas=schemas,
                    )
                )

        if capture_raw is not None:
            self.write_raw_snapshots(snapshots, capture_raw)
        total = len(cases)
        divisor = total or 1
        metrics = EvaluationMetrics(
            total=total,
            intent_accuracy=intent_hits / divisor,
            argument_accuracy=argument_hits / divisor,
            tool_accuracy=tool_hits / divisor,
            schema_compliance=schema_hits / divisor,
            latency_p50_ms=_percentile(latencies, 0.50),
            latency_p95_ms=_percentile(latencies, 0.95),
            latency_p99_ms=_percentile(latencies, 0.99),
        )
        per_intent = {name: statistics.mean(values) for name, values in by_intent.items()}
        previous_diff: dict[str, float] = {}
        if previous:
            for key in ("intent_accuracy", "argument_accuracy", "tool_accuracy", "schema_compliance"):
                previous_diff[key] = getattr(metrics, key) - getattr(previous.metrics, key)

        detailed_report = self._build_detailed_report(detailed_cases) if detailed else None
        return EvaluationReport(
            metrics=metrics,
            per_intent=per_intent,
            failures=failures,
            previous_diff=previous_diff,
            detailed=detailed_report,
            run_metadata=EvaluationRunMetadata(
                provider=metadata.get("provider", "unknown"),
                model=metadata.get("model", "unknown"),
                model_digest=metadata.get("model_digest", "unknown"),
                prompt_version=metadata.get("prompt_version", "unknown"),
                dataset_digest=metadata["dataset_digest"],
                baseline_report_digest=metadata.get("baseline_report_digest", "unknown"),
                baseline_snapshot_digest=metadata.get("baseline_snapshot_digest", "unknown"),
            ),
        )

    async def _score_detailed_case(
        self,
        *,
        case: EvaluationCase,
        snapshot: RawEvaluationSnapshot,
        result: IntentResult | None,
        schema_ok: bool,
        parse_error: str | None,
        schemas: Mapping[str, Mapping[str, JsonValue]],
    ) -> DetailedCaseResult:
        schema_invalid = _snapshot_has_schema_error(snapshot) or (snapshot.raw_result is not None and not schema_ok)
        if result is None:
            return DetailedCaseResult(
                id=case.id,
                raw_result=self._redact_report_arguments(snapshot.raw_result),
                model_error=parse_error,
                model_schema_invalid=schema_invalid,
                latency_ms=snapshot.latency_ms,
                route_source=snapshot.route_source,
                model_calls=snapshot.model_calls,
                schema_repaired=snapshot.schema_repaired,
                semantic_status="mismatch",
                semantic_reason="Model result was unavailable or structurally invalid",
                pipeline_outcome="not_run",
                pipeline_detail="The pipeline is never invoked for invalid model output",
            )

        raw_contract = check_contract(result.intent, result.arguments, schemas)
        raw_exact = all(result.arguments.get(key) == value for key, value in case.expected_arguments.items())
        normalized, rules, normalization_error = self._normalize(
            intent=result.intent,
            arguments=result.arguments,
            request_text=case.input_text,
        )
        normalized_contract = check_contract(result.intent, normalized, schemas) if normalization_error is None else None
        semantic = match_arguments(case, normalized if normalization_error is None else None)

        pipeline_outcome = "not_run"
        pipeline_detail = normalization_error
        pipeline_ok = False
        if normalization_error is None and normalized_contract is not None and normalized_contract.ok:
            dry_run = await self._dry_run_container.evaluate(
                case=case,
                intent=result.intent,
                arguments=normalized,
                raw_result=snapshot.raw_result or {},
            )
            pipeline_outcome = dry_run.outcome
            pipeline_detail = dry_run.detail
            pipeline_ok = outcome_matches(case.expected_pipeline_outcome, dry_run)

        end_to_end_ok = (
            result.intent == case.expected_intent
            and result.intent == case.expected_tool
            and normalized_contract is not None
            and normalized_contract.ok
            and semantic.status == "match"
            and pipeline_ok
        )
        return DetailedCaseResult(
            id=case.id,
            raw_result=self._redact_report_arguments(snapshot.raw_result),
            model_error=normalization_error,
            model_schema_invalid=schema_invalid,
            latency_ms=snapshot.latency_ms,
            route_source=snapshot.route_source,
            model_calls=snapshot.model_calls,
            schema_repaired=snapshot.schema_repaired,
            raw_intent_ok=result.intent == case.expected_intent,
            raw_tool_ok=result.intent == case.expected_tool,
            raw_contract_ok=raw_contract.ok,
            raw_exact_arguments_ok=raw_exact,
            normalized_arguments=self._redact_report_arguments(normalized) if normalization_error is None else None,
            normalization_rules=rules,
            normalized_contract_ok=bool(normalized_contract and normalized_contract.ok),
            semantic_status=semantic.status,
            semantic_reason=semantic.reason,
            pipeline_outcome=pipeline_outcome,
            pipeline_outcome_ok=pipeline_ok,
            pipeline_detail=pipeline_detail,
            end_to_end_ok=end_to_end_ok,
        )

    @staticmethod
    def _build_detailed_report(cases: list[DetailedCaseResult]) -> DetailedEvaluationReport:
        total = len(cases)
        divisor = total or 1
        matched = sum(case.semantic_status == "match" for case in cases)
        mismatched = sum(case.semantic_status == "mismatch" for case in cases)
        adjudicated = matched + mismatched
        metrics = DetailedEvaluationMetrics(
            total=total,
            raw_intent_accuracy=sum(case.raw_intent_ok for case in cases) / divisor,
            raw_tool_accuracy=sum(case.raw_tool_ok for case in cases) / divisor,
            raw_contract_accuracy=sum(case.raw_contract_ok for case in cases) / divisor,
            raw_exact_argument_accuracy=sum(case.raw_exact_arguments_ok for case in cases) / divisor,
            normalized_contract_accuracy=sum(case.normalized_contract_ok for case in cases) / divisor,
            semantic_match_rate=matched / divisor,
            semantic_adjudicated_accuracy=matched / (adjudicated or 1),
            semantic_coverage=adjudicated / divisor,
            needs_review_count=sum(case.semantic_status == "needs_review" for case in cases),
            model_schema_invalid_count=sum(case.model_schema_invalid for case in cases),
            end_to_end_accuracy=sum(case.end_to_end_ok for case in cases) / divisor,
        )
        return DetailedEvaluationReport(metrics=metrics, cases=cases)


__all__ = ["EvaluationService"]
