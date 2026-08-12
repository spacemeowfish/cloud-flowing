from __future__ import annotations

from pathlib import Path

import pytest

from agent_platform.adapters.mock_adapter import MockModelAdapter
from agent_platform.api.container import ApplicationContainer
from agent_platform.config import Settings
from agent_platform.core.interfaces import ModelAdapter
from agent_platform.core.model_gateway import ModelGateway
from agent_platform.models import (
    TaskCreate,
    TaskState,
    argument_extraction_contract,
    is_argument_extraction_schema,
    is_intent_classification_schema,
)
from agent_platform.tools.general_chat_tool import GeneralChatTool


class _AnswerAdapter(ModelAdapter):
    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.calls = 0

    async def generate(self, messages, response_schema, max_tokens=512):
        del messages, response_schema, max_tokens
        raise AssertionError("general_chat must not use structured generation")

    async def generate_text(self, messages, max_tokens=512):
        del messages, max_tokens
        self.calls += 1
        return self.answer

    async def close(self) -> None:
        return None


class _KnowledgeMisrouteAdapter(ModelAdapter):
    async def generate_text(self, messages, max_tokens=512):
        del messages, max_tokens
        return "二进制只使用 0 和 1，十进制使用 0 到 9。"

    async def generate(self, messages, response_schema, max_tokens=512):
        del max_tokens
        text = messages[-1].content
        if is_intent_classification_schema(response_schema):
            return {"intent": "knowledge_query", "confidence": 0.95}
        if is_argument_extraction_schema(response_schema):
            contract = argument_extraction_contract(response_schema)
            assert contract is not None
            intent, _ = contract
            if intent == "knowledge_query":
                return {"arguments": {"query": text}, "missing_fields": []}
            if intent == "reminder_create":
                return {"arguments": {"action": "delete_all"}, "missing_fields": ["when"]}
        return await MockModelAdapter().generate(messages, response_schema)

    async def close(self) -> None:
        return None


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        model_provider="mock",
        database_path=tmp_path / "agent.db",
        audit_dir=tmp_path / "audit",
        authorized_file_roots=[tmp_path / "files"],
        knowledge_roots=[tmp_path / "knowledge"],
        meeting_output_dir=tmp_path / "meetings",
        audit_flush_size=1,
    )


@pytest.mark.asyncio
async def test_deterministic_arithmetic_does_not_call_model():
    adapter = _AnswerAdapter("wrong")
    tool = GeneralChatTool(ModelGateway(adapter))
    receipt = await tool.execute({"text": "1+1=？"})
    assert receipt.success is True
    assert receipt.output["answer"] == "1+1 = 2"
    assert adapter.calls == 0

    chinese = await tool.execute({"text": "十二加八等于多少"})
    assert chinese.output["answer"] == "十二加八 = 20"
    assert adapter.calls == 0


@pytest.mark.asyncio
async def test_general_chat_rejects_internal_placeholder_or_prompt_echo():
    adapter = _AnswerAdapter("<FACT_n> 所有占位符必须原样保留")
    tool = GeneralChatTool(ModelGateway(adapter))
    receipt = await tool.execute({"text": "你好"})
    assert receipt.success is False
    assert receipt.error_code == "general_chat_quality_rejected"

    adapter = _AnswerAdapter("<think>没有闭合的思考过程")
    receipt = await GeneralChatTool(ModelGateway(adapter)).execute({"text": "你好"})
    assert receipt.success is False
    assert receipt.error_code == "general_chat_quality_rejected"


@pytest.mark.asyncio
async def test_general_chat_strips_one_closed_thinking_prefix():
    adapter = _AnswerAdapter("<think>私有推理，不应展示</think>最终答案")
    receipt = await GeneralChatTool(ModelGateway(adapter)).execute({"text": "你好"})
    assert receipt.success is True
    assert receipt.output == {"answer": "最终答案"}


@pytest.mark.asyncio
async def test_knowledge_empty_falls_back_once_for_non_local_question(tmp_path):
    container = ApplicationContainer.build(_settings(tmp_path))
    gateway = ModelGateway(_KnowledgeMisrouteAdapter())
    container.gateway = gateway
    container.agent._gateway = gateway
    container.registry.get("general_chat")._gateway = gateway  # type: ignore[attr-defined]
    await container.initialize()
    try:
        task = await container.agent.submit(TaskCreate(text="写出二进制与十进制的区别"))
        audit = await container.audit.by_task(task.id)
    finally:
        await container.close()
    assert task.state == TaskState.COMPLETED
    assert task.result["tool_name"] == "general_chat"
    assert any(event.decision == "knowledge_empty_to_general_chat" for event in audit)


@pytest.mark.asyncio
async def test_explicit_local_knowledge_no_hit_does_not_fallback(tmp_path):
    container = ApplicationContainer.build(_settings(tmp_path))
    gateway = ModelGateway(_KnowledgeMisrouteAdapter())
    container.gateway = gateway
    container.agent._gateway = gateway
    container.registry.get("general_chat")._gateway = gateway  # type: ignore[attr-defined]
    await container.initialize()
    try:
        task = await container.agent.submit(TaskCreate(text="查询知识库：不存在的内部制度"))
        audit = await container.audit.by_task(task.id)
    finally:
        await container.close()
    assert task.state == TaskState.COMPLETED
    assert task.result["tool_name"] == "knowledge_query"
    assert task.result["output"]["sources"] == []
    assert all(event.decision != "knowledge_empty_to_general_chat" for event in audit)


@pytest.mark.asyncio
async def test_schema_valid_arguments_clear_small_model_false_missing_fields(tmp_path):
    container = ApplicationContainer.build(_settings(tmp_path))
    gateway = ModelGateway(_KnowledgeMisrouteAdapter())
    container.gateway = gateway
    container.agent._gateway = gateway
    await container.initialize()
    try:
        task = await container.agent.submit(TaskCreate(text="删除全部提醒"))
    finally:
        await container.close()
    assert task.state == TaskState.AWAITING_CONFIRMATION
    assert task.context["missing_fields"] == []
    assert task.result["type"] == "risk_confirmation"
