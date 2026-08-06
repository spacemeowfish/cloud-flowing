"""Deterministic contract checks used by detailed evaluation.

The production tool metadata remains the source of truth.  Evaluation receives
the schemas from the initialized registry instead of keeping a second copy here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from jsonschema import Draft202012Validator
from pydantic import JsonValue


@dataclass(frozen=True)
class ContractCheckResult:
    ok: bool
    errors: tuple[str, ...] = ()


def check_contract(
    intent: str,
    arguments: Mapping[str, JsonValue],
    schemas: Mapping[str, Mapping[str, JsonValue]],
) -> ContractCheckResult:
    """Validate arguments against the registered schema for the selected intent."""

    schema = schemas.get(intent)
    if schema is None:
        return ContractCheckResult(False, (f"No registered schema for intent: {intent}",))
    errors = tuple(error.message for error in Draft202012Validator(dict(schema)).iter_errors(dict(arguments)))
    return ContractCheckResult(not errors, errors)


__all__ = ["ContractCheckResult", "check_contract"]
