"""Draft-only short-text processing with local fact preservation."""

import hashlib
import json
import re

from pydantic import JsonValue

from agent_platform.core.interfaces import Tool
from agent_platform.core.model_gateway import ModelGateway
from agent_platform.models import DataLevel, MessageRole, ModelMessage, RiskLevel, ToolMetadata, ToolReceipt


_FACT_PATTERN = re.compile(
    r"(?:1[3-9]\d{9}|20\d{2}[-/.年]\d{1,2}(?:[-/.月]\d{1,2}日?)?|\d+(?:\.\d+)?(?:元|万元|%|号)?|[A-Z][A-Za-z0-9_-]{2,})"
)


class TextProcessingTool(Tool):
    def __init__(self, gateway: ModelGateway) -> None:
        self._gateway = gateway

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="text_polish",
            description="Polish, summarize, tone-adjust, or draft short text without sending it",
            parameters_schema={
                "type": "object",
                "properties": {
                    "operation": {"type": "string", "enum": ["polish", "summarize", "tone_adjust", "draft", "confirm_send"]},
                    "text": {"type": "string", "minLength": 1, "maxLength": 10000},
                    "tone": {"type": "string", "enum": ["formal", "casual"]},
                    "target_length": {"type": "integer", "minimum": 10, "maximum": 10000},
                },
                "required": ["operation", "text"],
                "additionalProperties": False,
            },
            risk_level=RiskLevel.R1,
            data_level=DataLevel.D1,
            timeout_seconds=30,
        )

    def idempotency_key(self, arguments: dict[str, JsonValue]) -> str:
        value = json.dumps(arguments, ensure_ascii=False, sort_keys=True)
        return f"text:{hashlib.sha256(value.encode()).hexdigest()}"

    @staticmethod
    def _protect(text: str) -> tuple[str, dict[str, str]]:
        facts: dict[str, str] = {}

        def replace(match: re.Match[str]) -> str:
            key = f"<FACT_{len(facts)}>"
            facts[key] = match.group(0)
            return key

        return _FACT_PATTERN.sub(replace, text), facts

    @staticmethod
    def _fit_with_facts(text: str, facts: list[str], maximum: int) -> str:
        """Fit generated text while retaining each protected fact exactly once."""

        unique_facts = list(dict.fromkeys(facts))
        if len(text) <= maximum and all(value in text for value in unique_facts):
            return text
        fact_block = "；".join(unique_facts)
        if not fact_block:
            return text[:maximum]
        body = text
        for value in unique_facts:
            body = body.replace(value, "")
        body = re.sub(r"[；，、\s]+", " ", body).strip()
        separator = "；" if body else ""
        body_budget = max(0, maximum - len(fact_block) - len(separator))
        prefix = body[:body_budget].rstrip("；，、 ")
        return f"{prefix}{'；' if prefix else ''}{fact_block}"

    async def execute(self, arguments: dict[str, JsonValue]) -> ToolReceipt:
        operation = str(arguments["operation"])
        original = str(arguments["text"])
        if operation == "confirm_send":
            return ToolReceipt(
                tool_name=self.metadata.name,
                actual_arguments=arguments,
                success=True,
                output_summary="文本已确认，但本 MVP 不包含发送连接器",
                output={"text": original, "status": "confirmed_not_sent"},
                next_actions=["由已授权发送连接器继续处理"],
            )

        protected, facts = self._protect(original)
        operation_prompts = {
            "polish": f"请润色以下文字，修正错别字和不通顺的语句，使表达更专业流畅。所有 <FACT_n> 占位符必须原样保留。以JSON格式输出，格式为 {{\"text\": \"润色后的文本\"}}，不要加任何解释：\n{protected}",
            "summarize": f"请用简洁的语言总结以下内容。所有 <FACT_n> 占位符必须原样保留。以JSON格式输出，格式为 {{\"text\": \"总结内容\"}}，不要加任何解释：\n{protected}",
            "tone_adjust": f"请将以下文字的语气调整为{arguments.get('tone', 'formal')}风格。所有 <FACT_n> 占位符必须原样保留。以JSON格式输出，格式为 {{\"text\": \"调整后的文本\"}}，不要加任何解释：\n{protected}",
            "draft": f"请根据以下内容草拟一段正式的通知或消息。所有 <FACT_n> 占位符必须原样保留。以JSON格式输出，格式为 {{\"text\": \"草稿内容\"}}，不要加任何解释：\n{protected}",
        }
        prompt = operation_prompts.get(operation, protected)
        schema: dict[str, JsonValue] = {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        }
        generated = await self._gateway.generate([ModelMessage(role=MessageRole.USER, content=prompt)], schema, 1024)
        output = str(generated["text"])
        missing_placeholders = [placeholder for placeholder in facts if placeholder not in output]
        if missing_placeholders:
            output = f"{output.rstrip()} {' '.join(missing_placeholders)}".strip()
        for placeholder, value in facts.items():
            output = output.replace(placeholder, value)
        if operation == "summarize":
            target = int(arguments.get("target_length", max(10, len(original) // 2)))
            output = self._fit_with_facts(output, list(facts.values()), target)
        elif operation == "polish":
            output = self._fit_with_facts(output, list(facts.values()), max(1, len(original) * 2))
        draft = f"【草稿】{output}"
        return ToolReceipt(
            tool_name=self.metadata.name,
            actual_arguments=arguments,
            success=True,
            output_summary=draft,
            output={"text": draft, "status": "draft", "facts_preserved": list(facts.values())},
            next_actions=["确认内容后再发送"],
        )


__all__ = ["TextProcessingTool"]
