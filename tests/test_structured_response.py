import json

import pytest

from agent_platform.adapters.structured_response import (
    build_structured_system_prompt,
    effective_max_tokens,
    extract_flattened_messages,
    flatten_rkllm_prompt,
    parse_structured_response,
)
from agent_platform.core.errors import ModelError, ModelSchemaError
from agent_platform.models import INTENT_CLASSIFICATION_SCHEMA, INTENT_RESPONSE_SCHEMA, MessageRole, ModelMessage


SIMPLE_SCHEMA = {
    "type": "object",
    "properties": {"value": {"type": "string"}},
    "required": ["value"],
    "additionalProperties": False,
}


@pytest.mark.parametrize(
    "content",
    [
        '{"value":"ok"}',
        '```json\n{"value":"ok"}\n```',
        '<think>private reasoning</think>\n{"value":"ok"}',
        {"value": "ok"},
    ],
)
def test_structured_response_accepts_only_documented_complete_wrappers(content):
    assert parse_structured_response(content, SIMPLE_SCHEMA, error_detail="invalid") == {"value": "ok"}


@pytest.mark.parametrize(
    "content",
    [
        '{"value":"ok"}\nextra explanation',
        'answer: {"value":"ok"}',
        '{"value":"one"}{"value":"two"}',
        '{"value":"truncated"',
        '<think>unfinished reasoning\n{"value":"ok"}',
    ],
)
def test_structured_response_rejects_explanations_multiple_objects_and_truncation(content):
    with pytest.raises(ModelError, match="invalid"):
        parse_structured_response(content, SIMPLE_SCHEMA, error_detail="invalid")


def test_structured_response_enforces_schema():
    with pytest.raises(ModelSchemaError, match="invalid"):
        parse_structured_response('{"other":1}', SIMPLE_SCHEMA, error_detail="invalid")


def test_classification_prompt_contains_failure_driven_contrastive_boundaries():
    prompt = build_structured_system_prompt(INTENT_CLASSIFICATION_SCHEMA)
    assert "找会议记录 -> file_open" in prompt
    assert "待办：1小时后检查服务 -> reminder_create" in prompt
    assert "创建日程 每周一上午9点开会 -> schedule_manage" in prompt


def test_intent_token_limit_is_shared_and_respects_provider_ceiling():
    assert effective_max_tokens(INTENT_RESPONSE_SCHEMA, 512) == 192
    assert effective_max_tokens(INTENT_RESPONSE_SCHEMA, 100) == 100
    assert effective_max_tokens(SIMPLE_SCHEMA, 512, 256) == 256


def test_rkllm_flattened_prompt_round_trips_messages():
    messages = [ModelMessage(role=MessageRole.USER, content="查询保修期")]
    prompt = flatten_rkllm_prompt("system contract", messages)
    assert json.loads(prompt.split("CURRENT_CONVERSATION_JSON:\n", 1)[1].split("\nEND_", 1)[0])[0]["content"] == "查询保修期"
    assert extract_flattened_messages(prompt) == messages
