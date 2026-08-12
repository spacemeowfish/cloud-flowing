"""Draft-only short-text processing with local fact preservation."""

import hashlib
import json
import re

from pydantic import JsonValue

from agent_platform.core.errors import ModelError
from agent_platform.core.interfaces import Tool
from agent_platform.core.model_gateway import ModelGateway
from agent_platform.models import DataLevel, MessageRole, ModelMessage, RiskLevel, ToolMetadata, ToolReceipt


_FACT_PATTERN = re.compile(
    r"(?:1[3-9]\d{9}|20\d{2}[-/.年]\d{1,2}(?:[-/.月]\d{1,2}日?)?|\d+(?:\.\d+)?(?:元|万元|%|号)?|[A-Z][A-Za-z0-9_-]{2,})"
)
_COUNT_FACT_PATTERN = re.compile(
    r"[一二三四五六七八九十百千万两零〇壹贰叁肆伍陆柒捌玖拾佰仟]+"
    r"(?:个|项|条|份|次|名|台|套)[\u3400-\u9fff]{1,8}"
)
_ENUMERATION_PATTERN = re.compile(
    r"(?:分别)?(?:覆盖|包括|包含|涉及)([\u3400-\u9fffA-Za-z0-9_-]{1,30}"
    r"(?:、[\u3400-\u9fffA-Za-z0-9_-]{1,30})+"
    r"(?:和|及|与)[\u3400-\u9fffA-Za-z0-9_-]{1,30})"
)
_DRAFT_PREFIX = re.compile(r"^\s*(?:【草稿】|\[草稿\]|草稿(?:内容)?\s*[:：]?)\s*")
_PLACEHOLDER = re.compile(r"<(?:FACT_\d+|[^>]{0,40}占位符[^>]*)>")
_ANGLE_TOKEN = re.compile(r"<[^>\r\n]{1,80}>")
_LATEX_FACT_TOKEN = re.compile(r"\\?ext\{?FACT[_ ]?(?:\d+|n)\}?", re.IGNORECASE)
_INSTRUCTION_ECHO = re.compile(
    r"(?:请(?:注意|将|把)?\s*)?(?:所有\s*)?"
    r"(?:\\?ext\{?FACT[_ ]?(?:\d+|n)\}?|<FACT_\d+>|<FACT_n>|FACT[_ ]?n)?\s*"
    r"占位符(?:必须)?[^。！？!?；;\r\n]{0,80}?"
    r"(?:原样保留|保留原样|保持(?:原样|不变)|保持不变)[。！？!?；;]?",
    re.IGNORECASE,
)
_CJK = re.compile(r"[\u3400-\u9fff]")
_SCAFFOLDING_OUTPUTS = {"润色后的文本", "总结内容", "调整后的文本", "草稿内容"}
_INCOMPLETE_ENDING = re.compile(
    r"(?:的|地|得|和|与|及|或|但|而|在|于|为|将|以|请|把|对|向|从|至|等|所|所有|各|其|其中|确保|提交|完成|由于|因为|如果|当)$"
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

        protected = _FACT_PATTERN.sub(replace, text)
        lexical_facts = _COUNT_FACT_PATTERN.findall(text)
        for enumeration in _ENUMERATION_PATTERN.findall(text):
            lexical_facts.extend(
                item.strip()
                for item in re.split(r"、|和|及|与", enumeration)
                if item.strip()
            )
        for value in sorted(set(lexical_facts), key=len, reverse=True):
            if value not in protected:
                continue
            key = f"<FACT_{len(facts)}>"
            facts[key] = value
            protected = protected.replace(value, key)
        return protected, facts

    @staticmethod
    def _fit_with_facts(text: str, facts: list[str], maximum: int) -> str:
        """Keep complete model output; ``maximum`` is a prompt hint, not a cut-off."""

        del facts, maximum
        return text.strip()

    @staticmethod
    def _clean_model_output(output: str, facts: dict[str, str], source_text: str = "") -> str:
        """Remove internal markers and reject outputs that are visibly incomplete."""

        cleaned = _DRAFT_PREFIX.sub("", str(output).strip(), count=1).strip()
        # Small local models sometimes append the prompt's placeholder rule as if
        # it were user-facing prose.  Remove that sentence before quality checks;
        # if it was the whole answer, the caller falls back to the original text.
        cleaned = _INSTRUCTION_ECHO.sub(" ", cleaned)
        # Restore known protected facts before checking for leaked internal markers.
        for placeholder, value in facts.items():
            cleaned = cleaned.replace(placeholder, value)
        cleaned = _PLACEHOLDER.sub("", cleaned)
        cleaned = _LATEX_FACT_TOKEN.sub("", cleaned)
        # Unknown angle-bracket tokens are model scaffolding in this plain-text tool.
        cleaned = _ANGLE_TOKEN.sub("", cleaned).strip()
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if not cleaned or any(placeholder in cleaned for placeholder in facts):
            return ""
        if cleaned in _SCAFFOLDING_OUTPUTS:
            return ""
        # Chinese input must not silently turn into an English or structural token
        # response.  Returning the original is safer than exposing model scaffolding.
        if _CJK.search(source_text) and not _CJK.search(cleaned):
            return ""
        if any(token in cleaned for token in ("{", "}", "�")):
            return ""
        if _INCOMPLETE_ENDING.search(cleaned.rstrip("。！？!?；;")):
            return ""
        return cleaned

    @staticmethod
    def _casual_fallback(text: str) -> str:
        """Make the common short Chinese request less formal when the model echoes it."""

        casual = re.sub(r"请尽快提交(材料|资料)", r"麻烦尽快把\1交一下", text)
        casual = re.sub(r"^\s*请大家", "大家", casual)
        casual = re.sub(r"^\s*请", "麻烦", casual)
        if casual.strip() == text.strip():
            casual = f"和大家同步一下：{text.strip()}"
        return casual.strip()

    @classmethod
    def _model_error_fallback(cls, operation: str, text: str, tone: object) -> str:
        if operation == "draft":
            return f"通知：{text.strip()}"
        if operation == "tone_adjust" and tone == "casual":
            return cls._casual_fallback(text)
        return text.strip()

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
            "polish": f"请润色以下文字，修正错别字和不通顺的语句，使表达更专业流畅。输入中的尖括号标记只复制到 text 字段，不要复述规则。只输出JSON：{{\"text\": \"润色后的文本\"}}，不要加解释：\n{protected}",
            "summarize": f"请用简洁的语言总结以下内容。输入中的尖括号标记只复制到 text 字段，不要复述规则。只输出JSON：{{\"text\": \"总结内容\"}}，不要加解释：\n{protected}",
            "tone_adjust": f"请将以下文字的语气调整为{arguments.get('tone', 'formal')}风格。输入中的尖括号标记只复制到 text 字段，不要复述规则。只输出JSON：{{\"text\": \"调整后的文本\"}}，不要加解释：\n{protected}",
            "draft": f"请根据以下内容草拟一段正式的通知或消息。输入中的尖括号标记只复制到 text 字段，不要复述规则。只输出JSON：{{\"text\": \"草稿内容\"}}，不要加解释：\n{protected}",
        }
        prompt = operation_prompts.get(operation, protected)
        schema: dict[str, JsonValue] = {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        }
        messages = [ModelMessage(role=MessageRole.USER, content=prompt)]
        model_degraded = False
        try:
            generated = await self._gateway.generate(messages, schema, 1024)
        except ModelError as first_error:
            if first_error.retryable:
                raise
            try:
                generated = await self._gateway.generate(messages, schema, 1024)
            except ModelError as second_error:
                if second_error.retryable:
                    raise
                generated = {"text": self._model_error_fallback(operation, original, arguments.get("tone"))}
                model_degraded = True
        output = self._clean_model_output(str(generated["text"]), facts, original)
        # If a model drops a protected fact or returns a fragment, returning the
        # original is safer than manufacturing a sentence or leaking scaffolding.
        if not output or any(value not in output for value in facts.values()):
            output = original.strip()
        if operation == "tone_adjust" and arguments.get("tone") == "casual" and output == original.strip():
            output = self._casual_fallback(original)
        return ToolReceipt(
            tool_name=self.metadata.name,
            actual_arguments=arguments,
            success=True,
            output_summary=output,
            output={
                "text": output,
                "status": "draft",
                "facts_preserved": list(facts.values()),
                "model_degraded": model_degraded,
            },
            next_actions=["确认内容后再发送"],
        )


__all__ = ["TextProcessingTool"]
