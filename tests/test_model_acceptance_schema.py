"""Tests for the schema between model output and parameter normalization."""

from __future__ import annotations

from collections.abc import Mapping

import pytest
from jsonschema import Draft202012Validator, ValidationError
from pydantic import JsonValue

from agent_platform.core.tool_registry import ToolRegistry
from agent_platform.models import ToolMetadata, build_model_acceptance_schema, model_acceptance_contract


class _MetadataTool:
    def __init__(self, metadata: ToolMetadata) -> None:
        self._metadata = metadata

    @property
    def metadata(self) -> ToolMetadata:
        return self._metadata


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    specs = (
        ("file_open", ["query"], {"query": {"type": "string"}, "selected_path": {"type": "string"}}),
        ("general_chat", ["text"], {"text": {"type": "string"}}),
        ("knowledge_query", ["query"], {"query": {"type": "string"}}),
        ("meeting_process", ["source_path"], {"source_path": {"type": "string"}}),
        (
            "reminder_create",
            ["action"],
            {"action": {"type": "string"}, "id": {"type": "integer"}},
        ),
        (
            "todo_manage",
            ["action"],
            {"action": {"type": "string"}, "id": {"type": "integer"}, "title": {"type": "string"}},
        ),
        (
            "schedule_manage",
            ["action"],
            {"action": {"type": "string"}, "id": {"type": "integer"}, "title": {"type": "string"}},
        ),
        ("text_polish", ["operation", "text"], {"operation": {"type": "string"}, "text": {"type": "string"}}),
    )
    for intent, required, properties in specs:
        metadata = ToolMetadata(
            name=intent,
            description=intent,
            parameters_schema={
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        )
        registry.register(_MetadataTool(metadata))  # type: ignore[arg-type]
    registry.freeze()
    return registry


def _result(
    intent: str, arguments: Mapping[str, JsonValue], missing_fields: list[str] | None = None
) -> dict[str, JsonValue]:
    return {
        "intent": intent,
        "arguments": dict(arguments),
        "missing_fields": missing_fields or [],
        "confidence": 0.9,
    }


def test_runtime_schema_binds_intent_to_arguments_and_accepts_only_whitelisted_aliases():
    validator = Draft202012Validator(build_model_acceptance_schema(_registry()))

    validator.validate(_result("knowledge_query", {"question": "产品保修期"}))
    validator.validate(_result("file_open", {"keyword": "会议记录"}))
    with pytest.raises(ValidationError):
        validator.validate(_result("knowledge_query", {"keyword": "产品保修期"}))
    with pytest.raises(ValidationError):
        validator.validate(_result("file_open", {"query": "会议记录", "keyword": "重复"}))


def test_runtime_schema_permits_partial_arguments_only_with_missing_fields():
    validator = Draft202012Validator(build_model_acceptance_schema(_registry()))

    validator.validate(_result("text_polish", {"operation": "summarize"}, ["text"]))
    with pytest.raises(ValidationError):
        validator.validate(_result("text_polish", {"operation": "summarize"}))


def test_runtime_schema_leaves_conditional_execution_fields_for_post_normalization_validation():
    registry = _registry()
    reminder = registry.get("reminder_create")
    reminder._metadata = reminder.metadata.model_copy(  # type: ignore[attr-defined]
        update={
            "parameters_schema": {
                **reminder.metadata.parameters_schema,
                "allOf": [
                    {
                        "if": {"properties": {"action": {"const": "cancel"}}, "required": ["action"]},
                        "then": {"required": ["id"]},
                    }
                ],
            }
        }
    )
    validator = Draft202012Validator(build_model_acceptance_schema(registry))

    validator.validate(_result("reminder_create", {"action": "cancel", "id": 12}))
    validator.validate(_result("reminder_create", {"action": "cancel"}, ["id"]))
    # The model acceptance layer permits a raw cancel candidate so the
    # request-text normalizer can extract its numeric ID before the strict
    # ToolMetadata conditional contract is applied.
    validator.validate(_result("reminder_create", {"action": "cancel"}))


def test_prompt_contract_is_derived_from_registered_metadata():
    contract = model_acceptance_contract(build_model_acceptance_schema(_registry()))

    assert contract["knowledge_query"] == ("query", "question")
    assert contract["file_open"] == ("keyword", "query")
    assert contract["reminder_create"] == ("action", "id")


def test_model_contract_does_not_expose_confirmation_only_file_selection():
    validator = Draft202012Validator(build_model_acceptance_schema(_registry()))

    validator.validate(_result("file_open", {"query": "\u4f1a\u8bae\u8bb0\u5f55"}))
    with pytest.raises(ValidationError):
        validator.validate(_result("file_open", {"query": "\u4f1a\u8bae\u8bb0\u5f55", "selected_path": "C:/demo/a.txt"}))
