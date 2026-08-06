"""Conservative, deterministic semantic adjudication for fixed evaluation cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping

from pydantic import JsonValue

from agent_platform.models.evaluation import EvaluationCase


SemanticStatus = Literal["match", "mismatch", "needs_review"]
_ALIAS_INTENTS = {"knowledge_query", "file_open"}
_STRICT_FIELDS = {"source_path", "action", "id", "operation"}


@dataclass(frozen=True)
class SemanticMatchResult:
    status: SemanticStatus
    reason: str


def _conservative_text(value: str) -> str:
    """Only remove formatting noise; do not infer synonyms or remove meaning."""

    return "".join(value.casefold().split())


def _same_value(expected: JsonValue, actual: JsonValue) -> bool:
    if isinstance(expected, str) and isinstance(actual, str):
        return _conservative_text(expected) == _conservative_text(actual)
    return expected == actual


def _matches_alias(case: EvaluationCase, field: str, actual: JsonValue) -> bool:
    if field != "query" or case.expected_intent not in _ALIAS_INTENTS:
        return False
    return any(_same_value(alias, actual) for alias in case.aliases.get(field, []))


def match_arguments(case: EvaluationCase, arguments: Mapping[str, JsonValue] | None) -> SemanticMatchResult:
    """Match expected arguments without an LLM or undocumented fuzzy thresholds."""

    if arguments is None:
        return SemanticMatchResult("mismatch", "No model arguments available")
    if not case.expected_arguments:
        return SemanticMatchResult("needs_review", "Case has no expected arguments to adjudicate")

    for field, expected in case.expected_arguments.items():
        actual = arguments.get(field)
        if actual is None:
            return SemanticMatchResult("mismatch", f"Missing expected field: {field}")
        if _same_value(expected, actual):
            continue
        if _matches_alias(case, field, actual):
            continue
        if field in _STRICT_FIELDS:
            return SemanticMatchResult("mismatch", f"Strict field differs: {field}")
        return SemanticMatchResult("mismatch", f"Expected field differs: {field}")
    return SemanticMatchResult("match", "Expected arguments matched exactly or by registered alias")


__all__ = ["SemanticMatchResult", "SemanticStatus", "match_arguments"]
