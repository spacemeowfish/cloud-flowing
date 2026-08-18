"""Shared prompt, token-limit, and structured-response handling for LLM adapters."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence

from jsonschema import Draft202012Validator, ValidationError
from pydantic import JsonValue

from agent_platform.core.errors import ModelError, ModelSchemaError
from agent_platform.models import (
    INTENT_CLASSIFICATION_SCHEMA,
    ModelMessage,
    argument_extraction_contract,
    is_argument_extraction_schema,
    is_intent_classification_schema,
    is_model_acceptance_schema,
    model_acceptance_contract,
)


_THINK_PREFIX = re.compile(r"\A\s*<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE)
_JSON_FENCE = re.compile(r"\A\s*```(?:json)?\s*(.*?)\s*```\s*\Z", re.DOTALL | re.IGNORECASE)
_CONVERSATION_MARKER = "CURRENT_CONVERSATION_JSON:"
INTENT_PROMPT_VERSION = "qwen2.5-3b-staged-v4.0-document-boundaries"


def is_intent_response_schema(schema: dict[str, JsonValue]) -> bool:
    return (
        is_model_acceptance_schema(schema)
        or is_argument_extraction_schema(schema)
        or is_intent_classification_schema(schema)
        or "intent" in schema.get("properties", {})
    )


def effective_max_tokens(schema: dict[str, JsonValue], requested: int, provider_limit: int | None = None) -> int:
    """Apply the shared intent cap and an optional provider-specific ceiling."""

    limit = min(requested, 192) if is_intent_response_schema(schema) else requested
    return min(limit, provider_limit) if provider_limit is not None else limit


def build_structured_system_prompt(response_schema: dict[str, JsonValue]) -> str:
    extraction_contract = argument_extraction_contract(response_schema)
    if extraction_contract is not None:
        intent, fields = extraction_contract
        return _argument_extraction_system_prompt(intent, fields, response_schema)
    if is_intent_classification_schema(response_schema):
        return _classification_system_prompt()
    if is_intent_response_schema(response_schema):
        return _intent_system_prompt(response_schema)
    schema_json = json.dumps(response_schema, ensure_ascii=False)
    return (
        "You are a helpful assistant. Process the user's Chinese request. "
        "Respond ONLY with a JSON object matching the given schema. No markdown, no explanation.\n"
        f"Schema: {schema_json}"
    )


def flatten_rkllm_prompt(system_content: str, messages: Sequence[ModelMessage]) -> str:
    """Put the full contract in one user prompt for RKLLM Server compatibility."""

    conversation = [message.model_dump(mode="json") for message in messages]
    return (
        f"{system_content}\n\n"
        f"{_CONVERSATION_MARKER}\n"
        f"{json.dumps(conversation, ensure_ascii=False)}\n"
        "END_CURRENT_CONVERSATION\n"
        "Follow the system contract above and output only the required JSON object."
    )


def parse_structured_response(
    content: JsonValue,
    response_schema: dict[str, JsonValue],
    *,
    error_detail: str,
) -> dict[str, JsonValue]:
    """Parse one complete JSON object while allowing only documented wrappers."""

    try:
        if isinstance(content, dict):
            result = content
        elif isinstance(content, str):
            text = _THINK_PREFIX.sub("", content, count=1)
            fence = _JSON_FENCE.fullmatch(text)
            if fence:
                text = fence.group(1)
            text = text.strip()
            result, end = json.JSONDecoder().raw_decode(text)
            if text[end:].strip():
                raise ValueError("unexpected text after JSON object")
            if not isinstance(result, dict):
                raise TypeError("model content is not an object")
        else:
            raise TypeError("model content is not text or an object")
    except (ValueError, TypeError) as exc:
        raise ModelError(error_detail) from exc
    try:
        Draft202012Validator(response_schema).validate(result)
    except ValidationError as exc:
        path = ".".join(str(part) for part in exc.absolute_path) or "$"
        validation_error = f"{path}: {exc.message}"
        raise ModelSchemaError(
            error_detail,
            raw_result=result,
            validation_errors=(validation_error,),
        ) from exc
    return result


def extract_flattened_messages(prompt: str) -> list[ModelMessage]:
    """Recover the embedded conversation for the local protocol simulator."""

    marker_index = prompt.rfind(_CONVERSATION_MARKER)
    if marker_index < 0:
        raise ValueError("RKLLM prompt does not contain the conversation marker")
    payload_start = marker_index + len(_CONVERSATION_MARKER)
    payload_text = prompt[payload_start:].lstrip()
    payload, _ = json.JSONDecoder().raw_decode(payload_text)
    if not isinstance(payload, list):
        raise ValueError("embedded conversation is not a list")
    return [ModelMessage.model_validate(item) for item in payload]


def extract_schema_from_prompt(prompt: str) -> dict[str, JsonValue] | None:
    """Read a generic response Schema embedded by build_structured_system_prompt."""

    if "CONTRACT_KIND:intent_classification" in prompt:
        return INTENT_CLASSIFICATION_SCHEMA
    marker = "Schema: "
    marker_index = prompt.find(marker)
    if marker_index < 0:
        return None
    payload, _ = json.JSONDecoder().raw_decode(prompt[marker_index + len(marker) :])
    return payload if isinstance(payload, dict) else None


def _intent_system_prompt(response_schema: dict[str, JsonValue]) -> str:
    """Return a compact, Chinese-first contract suited to the local 3B model."""

    contract = model_acceptance_contract(response_schema)
    if len(contract) == 1:
        intent, names = next(iter(contract.items()))
        return _selected_intent_system_prompt(intent, names)
    fields = contract or {
        "file_open": ("query",),
        "general_chat": ("text",),
        "knowledge_query": ("query",),
        "meeting_process": ("source_path",),
        "reminder_create": ("action", "text", "when", "id", "scope"),
        "todo_manage": ("action", "id", "title", "priority", "title_query"),
        "schedule_manage": ("action", "id", "title", "start_text", "recurrence", "weekdays", "range", "title_query"),
        "text_polish": ("operation", "text", "tone", "target_length"),
    }
    field_lines = "\n".join(f"- {intent}: {', '.join(names)}" for intent, names in fields.items())
    examples = (
        "用户：找会议记录\n"
        "助手：{\"intent\":\"file_open\",\"arguments\":{\"query\":\"会议记录\"},\"missing_fields\":[],\"confidence\":0.95}\n\n"
        "用户：查询产品保修期\n"
        "助手：{\"intent\":\"knowledge_query\",\"arguments\":{\"query\":\"产品保修期\"},\"missing_fields\":[],\"confidence\":0.95}\n\n"
        "用户：1+1等于多少\n"
        "助手：{\"intent\":\"general_chat\",\"arguments\":{\"text\":\"1+1等于多少\"},\"missing_fields\":[],\"confidence\":0.99}\n\n"
        "用户：取消提醒 12\n"
        "助手：{\"intent\":\"reminder_create\",\"arguments\":{\"action\":\"cancel\",\"id\":12},\"missing_fields\":[],\"confidence\":0.97}\n\n"
        "用户：总结这段：本季度完成了三个项目\n"
        "助手：{\"intent\":\"text_polish\",\"arguments\":{\"operation\":\"summarize\",\"text\":\"本季度完成了三个项目\"},\"missing_fields\":[],\"confidence\":0.95}\n\n"
        "用户：添加待办 提交报告，高优先级\n"
        "助手：{\"intent\":\"todo_manage\",\"arguments\":{\"action\":\"create\",\"title\":\"提交报告\",\"priority\":\"high\"},\"missing_fields\":[],\"confidence\":0.96}\n\n"
        "用户：完成待办 提交报告\n"
        "助手：{\"intent\":\"todo_manage\",\"arguments\":{\"action\":\"query\",\"title_query\":\"提交报告\"},\"missing_fields\":[],\"confidence\":0.96}\n\n"
        "用户：创建日程 每周一三五上午9点站会\n"
        "助手：{\"intent\":\"schedule_manage\",\"arguments\":{\"action\":\"create\",\"title\":\"站会\",\"start_text\":\"每周一三五上午9点\",\"recurrence\":\"weekly\",\"weekdays\":[0,2,4]},\"missing_fields\":[],\"confidence\":0.96}\n\n"
        "用户：取消日程 8\n"
        "助手：{\"intent\":\"schedule_manage\",\"arguments\":{\"action\":\"cancel\",\"id\":8},\"missing_fields\":[],\"confidence\":0.97}"
    )
    return (
        "你是本地 AI 助手的意图和参数提取器，只处理用户的中文请求。\n"
        "只能输出一个合法 JSON 对象，不得输出 Markdown、解释、注释或额外字符。\n"
        "固定格式：{\"intent\":\"...\",\"arguments\":{},\"missing_fields\":[],\"confidence\":0.95}\n"
        "missing_fields 必须是 JSON 数组；信息足够时始终为 []，不能写成 missing_fields[]。\n\n"
        "可选意图和允许的参数字段：\n"
        f"{field_lines}\n\n"
        "规则：\n"
        "- file_open 用于找或打开文件；knowledge_query 只用于查询已授权本地知识；general_chat 用于不属于其他工具的数学、常识、闲聊和翻译；meeting_process 用于从会议文本路径生成纪要。\n"
        "- reminder_create.action 只能是 create、query、cancel、complete、delete_all。查看未来提醒用 query。\n"
        "- 只有明确“取消提醒 + 数字 ID”才用 cancel；只有明确“删除所有/全部提醒”才用 delete_all。不得编造路径、ID 或时间。\n"
        "- todo_manage 的 complete、delete、update 只能在用户给出数字 ID 时使用；按标题完成或删除必须用 query + title_query 返回候选。\n"
        "- schedule_manage 的 cancel 只能在用户给出数字 ID 时使用；按标题取消必须用 query + title_query。日程创建需 title 和 start_text，重复日程需给出 recurrence，weekly 还需 weekdays。\n"
        "- Windows 路径在 JSON 中用正斜杠，例如 C:/demo/m1.txt；系统会恢复原始路径。\n"
        "- 以“缩写”或“总结”开头时 operation=summarize；以“草拟”开头时 operation=draft；包含“调整语气”或“语气调整”时 operation=tone_adjust；其余润色、改写、澄清 operation=polish。\n"
        "- 优先使用 query；兼容字段 question、keyword 只在确实不可避免时使用。\n\n"
        f"示例：\n{examples}"
    )


def _classification_system_prompt() -> str:
    return (
        "CONTRACT_KIND:intent_classification\n"
        "你只判断用户请求属于哪个意图，不提取参数。只能输出一个 JSON 对象："
        "{\"intent\":\"...\",\"confidence\":0.95}。不得输出 arguments、解释或 Markdown。\n"
        "可选意图：file_open, general_chat, knowledge_query, meeting_process, reminder_create, todo_manage, schedule_manage, text_polish, clarify, unsupported。\n"
        "边界规则和对比示例：\n"
        "- 查看/看看项目周报 -> file_open；项目周报中完成了什么 -> knowledge_query；总结项目周报 -> knowledge_query，不把文件名当作正文。\n"
        "- 查询会议室使用规则 -> knowledge_query；预约 A301 会议室 -> schedule_manage（只创建本地日程，不代表房间锁定）。\n"
        "- 找会议记录 -> file_open；整理会议纪要 C:/docs/周会.txt -> meeting_process，不能编造路径。\n"
        "- 待办：1小时后检查服务 -> reminder_create；添加待办 检查服务 -> todo_manage。\n"
        "- 每周一上午9点提醒我开会 -> reminder_create；创建日程 每周一上午9点开会 -> schedule_manage。\n"
        "- 取消日程 项目会 -> schedule_manage；取消提醒 12 -> reminder_create。\n"
        "- 总结这段：本季度完成三个项目 -> text_polish；提醒功能怎么用 -> knowledge_query；待办清单文件在哪 -> file_open。\n"
        "- 日程管理制度是什么 -> knowledge_query；本周有什么会议 -> 只有存在真实本地日程数据时才 schedule_manage，否则 clarify。\n"
        "- 多份周报未给日期或能力不足 -> clarify；真实会议室预约、外部系统连接等当前不支持 -> unsupported。\n"
        "- 1+1等于多少、明确翻译、普通外部常识和闲聊 -> general_chat；不要因为问号或单个名词选择工具。"
    )


def _selected_intent_system_prompt(intent: str, fields: tuple[str, ...]) -> str:
    examples = {
        "file_open": "打开预算表.xlsx => {\"intent\":\"file_open\",\"arguments\":{\"query\":\"预算表.xlsx\"},\"missing_fields\":[],\"confidence\":0.98}",
        "general_chat": "1+1等于多少 => {\"intent\":\"general_chat\",\"arguments\":{\"text\":\"1+1等于多少\"},\"missing_fields\":[],\"confidence\":0.99}",
        "knowledge_query": "公司报销标准是什么 => {\"intent\":\"knowledge_query\",\"arguments\":{\"query\":\"公司报销标准是什么\"},\"missing_fields\":[],\"confidence\":0.96}",
        "meeting_process": "会议文稿在 C:/docs/周会.txt => {\"intent\":\"meeting_process\",\"arguments\":{\"source_path\":\"C:/docs/周会.txt\"},\"missing_fields\":[],\"confidence\":0.98}",
        "reminder_create": "提醒我30分钟后开会 => {\"intent\":\"reminder_create\",\"arguments\":{\"action\":\"create\",\"text\":\"开会\",\"when\":\"30分钟后\"},\"missing_fields\":[],\"confidence\":0.98}",
        "todo_manage": "完成待办 提交报告 => {\"intent\":\"todo_manage\",\"arguments\":{\"action\":\"query\",\"title_query\":\"提交报告\"},\"missing_fields\":[],\"confidence\":0.97}",
        "schedule_manage": "取消日程 12 => {\"intent\":\"schedule_manage\",\"arguments\":{\"action\":\"cancel\",\"id\":12},\"missing_fields\":[],\"confidence\":0.99}",
        "text_polish": "总结这段：本季度完成三个项目 => {\"intent\":\"text_polish\",\"arguments\":{\"operation\":\"summarize\",\"text\":\"本季度完成三个项目\"},\"missing_fields\":[],\"confidence\":0.98}",
    }
    special_rules = {
        "reminder_create": "action 只能为 create/query/cancel/complete/delete_all；create 使用 text 和 when，不得使用 start_text/title。",
        "todo_manage": "按标题完成或删除必须 query + title_query；complete/delete/update 只接受用户明确给出的数字 id。",
        "schedule_manage": "创建使用 title/start_text；重复日程使用 recurrence，weekly 还需 weekdays；按标题取消先 query + title_query。",
        "meeting_process": "只提取一个绝对 txt/md 路径；Windows 路径在 JSON 中使用正斜杠。",
        "text_polish": "总结/缩写=summarize，草拟=draft，语气调整=tone_adjust，其余改写/润色=polish；不要输出 tone:null。",
        "general_chat": "只把用户原始问题放入 text；不得改写成知识库查询或添加其他字段。",
    }
    allowed = ", ".join(fields)
    return (
        f"CONTRACT_KIND:selected_intent\nSELECTED_INTENT:{intent}\n"
        f"意图已经确定为 {intent}，不得改成其他意图。只提取参数。\n"
        "只能输出一个合法 JSON 对象，固定顶层字段为 intent、arguments、missing_fields、confidence；不得输出 Markdown 或解释。\n"
        f"arguments 只允许这些字段：{allowed}。不得把 missing_fields 或 confidence 放进 arguments。\n"
        f"{special_rules.get(intent, '')}\n"
        "信息足够时 missing_fields 必须为 []；不得编造 ID、路径、时间或字段。\n"
        f"示例：{examples[intent]}"
    )


def _argument_extraction_system_prompt(
    intent: str, fields: tuple[str, ...], response_schema: dict[str, JsonValue]
) -> str:
    examples = {
        "file_open": [
            "打开预算表.xlsx => {\"arguments\":{\"query\":\"预算表.xlsx\"},\"missing_fields\":[]}",
            "找文件在哪：设备手册 => {\"arguments\":{\"query\":\"设备手册\"},\"missing_fields\":[]}",
        ],
        "general_chat": [
            "1+1等于多少 => {\"arguments\":{\"text\":\"1+1等于多少\"},\"missing_fields\":[]}",
            "把你好翻译成英文 => {\"arguments\":{\"text\":\"把你好翻译成英文\"},\"missing_fields\":[]}",
        ],
        "knowledge_query": [
            "项目周报中完成了什么 => {\"arguments\":{\"query\":\"项目周报中完成了什么\"},\"missing_fields\":[]}",
            "公司报销标准是什么 => {\"arguments\":{\"query\":\"公司报销标准是什么\"},\"missing_fields\":[]}",
        ],
        "meeting_process": [
            "会议文稿在 C:/docs/周会.txt => {\"arguments\":{\"source_path\":\"C:/docs/周会.txt\"},\"missing_fields\":[]}",
        ],
        "reminder_create": [
            "提醒我30分钟后开会 => {\"arguments\":{\"action\":\"create\",\"text\":\"开会\",\"when\":\"30分钟后\"},\"missing_fields\":[]}",
            "查看未来7天提醒 => {\"arguments\":{\"action\":\"query\",\"scope\":\"next_7_days\"},\"missing_fields\":[]}",
            "取消提醒 12 => {\"arguments\":{\"action\":\"cancel\",\"id\":12},\"missing_fields\":[]}",
        ],
        "todo_manage": [
            "添加待办 整理材料，高优先级 => {\"arguments\":{\"action\":\"create\",\"title\":\"整理材料\",\"priority\":\"high\"},\"missing_fields\":[]}",
            "完成待办 提交报告 => {\"arguments\":{\"action\":\"query\",\"title_query\":\"提交报告\"},\"missing_fields\":[]}",
            "删除待办 12 => {\"arguments\":{\"action\":\"delete\",\"id\":12},\"missing_fields\":[]}",
        ],
        "schedule_manage": [
            "预约 A301 会议室 => {\"arguments\":{\"action\":\"create\",\"title\":\"会议\",\"location\":\"A301\",\"start_text\":\"今天\"},\"missing_fields\":[]}",
            "创建日程 明天下午2点项目会 => {\"arguments\":{\"action\":\"create\",\"title\":\"项目会\",\"start_text\":\"明天下午2点\"},\"missing_fields\":[]}",
            "今天下午有什么安排 => {\"arguments\":{\"action\":\"query\",\"range\":\"today\"},\"missing_fields\":[]}",
            "取消日程 12 => {\"arguments\":{\"action\":\"cancel\",\"id\":12},\"missing_fields\":[]}",
        ],
        "text_polish": [
            "润色：预算为300万元 => {\"arguments\":{\"operation\":\"polish\",\"text\":\"预算为300万元\"},\"missing_fields\":[]}",
            "总结这段：完成三个项目 => {\"arguments\":{\"operation\":\"summarize\",\"text\":\"完成三个项目\"},\"missing_fields\":[]}",
            "语气调整：请尽快提交 => {\"arguments\":{\"operation\":\"tone_adjust\",\"text\":\"请尽快提交\"},\"missing_fields\":[]}",
        ],
    }
    special_rules = {
        "reminder_create": "action 必须是 create/query/cancel/complete/delete_all；create 不得使用 start_text/title。",
        "todo_manage": "action 必须是 create/query/update/complete/delete；按标题完成或删除使用 query + title_query。",
        "schedule_manage": "action 必须是 create/query/cancel；创建必须包含 title 和 start_text；location 只是本地记录，不代表房间锁定；按标题取消先 query + title_query。",
        "text_polish": "arguments 必须包含 operation 和 text；不得输出 tone:null。",
        "general_chat": "arguments 必须且只能包含非空 text；保留用户原始问题。",
    }
    schema_json = json.dumps(response_schema, ensure_ascii=False, separators=(",", ":"))
    return (
        f"CONTRACT_KIND:argument_extraction\nARGUMENT_EXTRACTION_INTENT:{intent}\n"
        f"意图已由系统确定为 {intent}。你只提取参数，不得输出 intent 或 confidence。\n"
        "只输出一个 JSON 对象，顶层必须且只能有 arguments、missing_fields。"
        "固定格式：{\"arguments\":{},\"missing_fields\":[]}。不得输出解释或 Markdown。\n"
        f"arguments 只允许字段：{', '.join(fields)}。{special_rules.get(intent, '')}\n"
        "信息足够时 missing_fields 必须为 []；不得编造 ID、路径或时间。\n"
        f"示例：\n" + "\n".join(examples[intent]) + "\n"
        f"Schema: {schema_json}"
    )


__all__ = [
    "INTENT_PROMPT_VERSION",
    "build_structured_system_prompt",
    "effective_max_tokens",
    "extract_flattened_messages",
    "extract_schema_from_prompt",
    "flatten_rkllm_prompt",
    "is_intent_response_schema",
    "parse_structured_response",
]
