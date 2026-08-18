"""Build the schema accepted between an intent model and normalization."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, cast

from pydantic import JsonValue

if TYPE_CHECKING:
    from agent_platform.core.tool_registry import ToolRegistry


INTENT_NAMES = (
    "file_open",
    "general_chat",
    "knowledge_query",
    "meeting_process",
    "reminder_create",
    "todo_manage",
    "schedule_manage",
    "text_polish",
)
TERMINAL_INTENT_NAMES = ("clarify", "unsupported")
CLASSIFICATION_INTENT_NAMES = (*INTENT_NAMES, *TERMINAL_INTENT_NAMES)

# These aliases are valid only in model output. Parameter normalization must
# convert them before strict ToolMetadata validation and tool execution.
MODEL_ARGUMENT_ALIASES: dict[str, dict[str, str]] = {
    "file_open": {"keyword": "query"},
    "knowledge_query": {"question": "query"},
}

# These values are selected only after a search/preview or explicit
# confirmation. The first-pass model must not invent them or mark them missing.
# The strict tool schema still validates them at the execution boundary.
MODEL_EXCLUDED_ARGUMENTS: dict[str, frozenset[str]] = {
    "file_open": frozenset({"selected_path"}),
}

_SCHEMA_MARKER = "agent-platform-model-acceptance-v1"
_CLASSIFICATION_MARKER = "agent-platform-intent-classification-v1"
_ARGUMENT_EXTRACTION_MARKER = "agent-platform-argument-extraction-v1"


INTENT_CLASSIFICATION_SCHEMA: dict[str, JsonValue] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$comment": _CLASSIFICATION_MARKER,
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": list(CLASSIFICATION_INTENT_NAMES)},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["intent", "confidence"],
    "additionalProperties": False,
}


def build_model_acceptance_schema(registry: ToolRegistry) -> dict[str, JsonValue]:
    """Create an intent-bound acceptance schema from registered tool metadata."""

    branches: list[dict[str, JsonValue]] = []
    for intent in INTENT_NAMES:
        branches.extend(_intent_branches(intent, registry.get(intent).metadata.parameters_schema))
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$comment": _SCHEMA_MARKER,
        "oneOf": branches,
    }


def is_model_acceptance_schema(schema: Mapping[str, JsonValue]) -> bool:
    return schema.get("$comment") == _SCHEMA_MARKER


def is_intent_classification_schema(schema: Mapping[str, JsonValue]) -> bool:
    return schema.get("$comment") == _CLASSIFICATION_MARKER


def is_argument_extraction_schema(schema: Mapping[str, JsonValue]) -> bool:
    return schema.get("$comment") == _ARGUMENT_EXTRACTION_MARKER


def select_model_acceptance_schema(
    schema: Mapping[str, JsonValue], intent: str
) -> dict[str, JsonValue]:
    """Restrict a full model acceptance schema to one already-selected intent."""

    if not is_model_acceptance_schema(schema):
        raise ValueError("Expected a model acceptance schema")
    if intent not in INTENT_NAMES:
        raise ValueError(f"Unsupported intent: {intent}")
    branches: list[JsonValue] = []
    for branch in _list(schema.get("oneOf")):
        if not isinstance(branch, Mapping):
            continue
        properties = _mapping(branch.get("properties"))
        intent_schema = _mapping(properties.get("intent"))
        if intent_schema.get("const") == intent:
            branches.append(cast(JsonValue, dict(branch)))
    if not branches:
        raise ValueError(f"Acceptance schema has no branch for intent: {intent}")
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$comment": _SCHEMA_MARKER,
        "oneOf": branches,
    }


def build_argument_extraction_schema(
    schema: Mapping[str, JsonValue], intent: str
) -> dict[str, JsonValue]:
    """Remove already-decided intent/confidence fields from the parameter stage."""

    selected = select_model_acceptance_schema(schema, intent)
    branches: list[JsonValue] = []
    for branch in _list(selected.get("oneOf")):
        branch_mapping = _mapping(branch)
        properties = _mapping(branch_mapping.get("properties"))
        branches.append(
            {
                "type": "object",
                "properties": {
                    "arguments": cast(JsonValue, dict(_mapping(properties.get("arguments")))),
                    "missing_fields": cast(JsonValue, dict(_mapping(properties.get("missing_fields")))),
                },
                "required": ["arguments", "missing_fields"],
                "additionalProperties": False,
            }
        )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$comment": _ARGUMENT_EXTRACTION_MARKER,
        "x-selected-intent": intent,
        "oneOf": branches,
    }


def argument_extraction_contract(schema: Mapping[str, JsonValue]) -> tuple[str, tuple[str, ...]] | None:
    if not is_argument_extraction_schema(schema):
        return None
    intent = schema.get("x-selected-intent")
    branches = _list(schema.get("oneOf"))
    if not isinstance(intent, str) or not branches:
        return None
    first = _mapping(branches[0])
    arguments = _mapping(_mapping(first.get("properties")).get("arguments"))
    fields = tuple(sorted(_mapping(arguments.get("properties"))))
    return intent, fields


def model_acceptance_contract(schema: Mapping[str, JsonValue]) -> dict[str, tuple[str, ...]]:
    """Extract compact intent/field information for the model prompt."""

    if not is_model_acceptance_schema(schema):
        return {}
    result: dict[str, tuple[str, ...]] = {}
    one_of = schema.get("oneOf", [])
    if not isinstance(one_of, list):
        return result
    for branch in one_of:
        if not isinstance(branch, dict):
            continue
        properties = _mapping(branch.get("properties"))
        intent_schema = _mapping(properties.get("intent"))
        arguments_schema = _mapping(properties.get("arguments"))
        intent = intent_schema.get("const")
        arguments = _mapping(arguments_schema.get("properties"))
        if isinstance(intent, str):
            result[intent] = tuple(sorted(arguments))
    return result


def _intent_branches(intent: str, tool_schema: Mapping[str, JsonValue]) -> list[dict[str, JsonValue]]:
    canonical_properties = _mapping(tool_schema.get("properties"))
    model_properties = {
        name: field_schema
        for name, field_schema in canonical_properties.items()
        if name not in MODEL_EXCLUDED_ARGUMENTS.get(intent, frozenset())
    }
    canonical_names = tuple(model_properties)
    aliases = MODEL_ARGUMENT_ALIASES.get(intent, {})
    required = [
        str(name)
        for name in _list(tool_schema.get("required"))
        if str(name) in model_properties
    ]
    argument_properties = _model_properties(model_properties, aliases)
    arguments_base: dict[str, JsonValue] = {
        "type": "object",
        "properties": argument_properties,
        "additionalProperties": False,
    }
    alias_exclusion = _exclusive_aliases(aliases)
    if alias_exclusion:
        arguments_base["allOf"] = alias_exclusion

    base_properties: dict[str, JsonValue] = {
        "intent": {"const": intent},
        "arguments": arguments_base,
        "missing_fields": {
            "type": "array",
            "items": {"type": "string", "enum": list(canonical_names)},
            "uniqueItems": True,
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    }
    complete = {
        "type": "object",
        "properties": {
            **base_properties,
            "arguments": _complete_arguments_schema(arguments_base, required, aliases),
            "missing_fields": {"type": "array", "maxItems": 0},
        },
        "required": ["intent", "arguments", "missing_fields", "confidence"],
        "additionalProperties": False,
    }
    partial = {
        "type": "object",
        "properties": {
            **base_properties,
            "missing_fields": {
                "type": "array",
                "items": {"type": "string", "enum": list(canonical_names)},
                "minItems": 1,
                "uniqueItems": True,
            },
        },
        "required": ["intent", "arguments", "missing_fields", "confidence"],
        "additionalProperties": False,
    }
    return [complete, partial]


def _model_properties(
    canonical_properties: Mapping[str, JsonValue], aliases: Mapping[str, str]
) -> dict[str, JsonValue]:
    properties: dict[str, JsonValue] = {}
    for name, field_schema in canonical_properties.items():
        source = _mapping(field_schema)
        properties[name] = {
            key: value
            for key, value in source.items()
            if key in {"type", "enum", "minimum", "maximum", "minLength", "maxLength", "items"}
        }
    for alias, canonical in aliases.items():
        properties[alias] = dict(_mapping(properties.get(canonical)))
    return properties


def _complete_arguments_schema(
    arguments_base: Mapping[str, JsonValue],
    required: list[str],
    aliases: Mapping[str, str],
) -> dict[str, JsonValue]:
    result = dict(arguments_base)
    required_aliases = {canonical: alias for alias, canonical in aliases.items() if canonical in required}
    if required_aliases:
        alternatives: list[dict[str, JsonValue]] = [
            {
                "required": required,
                "not": {"anyOf": [{"required": [alias]} for alias in required_aliases.values()]},
            }
        ]
        for canonical, alias in required_aliases.items():
            alternatives.append(
                {
                    "required": [alias if name == canonical else name for name in required],
                    "not": {"required": [canonical]},
                }
            )
        result["oneOf"] = alternatives
    else:
        result["required"] = required

    return result


def _exclusive_aliases(aliases: Mapping[str, str]) -> list[dict[str, JsonValue]]:
    return [{"not": {"required": [alias, canonical]}} for alias, canonical in aliases.items()]


def _mapping(value: object) -> Mapping[str, JsonValue]:
    return cast(Mapping[str, JsonValue], value) if isinstance(value, Mapping) else {}


def _list(value: object) -> list[JsonValue]:
    return list(cast(list[JsonValue], value)) if isinstance(value, list) else []


__all__ = [
    "argument_extraction_contract",
    "build_argument_extraction_schema",
    "INTENT_CLASSIFICATION_SCHEMA",
    "INTENT_NAMES",
    "TERMINAL_INTENT_NAMES",
    "CLASSIFICATION_INTENT_NAMES",
    "MODEL_ARGUMENT_ALIASES",
    "MODEL_EXCLUDED_ARGUMENTS",
    "build_model_acceptance_schema",
    "is_intent_classification_schema",
    "is_argument_extraction_schema",
    "is_model_acceptance_schema",
    "model_acceptance_contract",
    "select_model_acceptance_schema",
]
