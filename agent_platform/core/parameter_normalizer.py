"""Deterministic, pre-validation repairs for model-produced tool arguments."""

from collections.abc import Mapping
from dataclasses import dataclass
import re

from pydantic import JsonValue


_WINDOWS_SOURCE_PATH = re.compile(
    r"(?<![A-Za-z0-9])([A-Za-z]:[\\/][^<>:\"|?*\r\n]*?\.(?:txt|md))",
    re.IGNORECASE,
)
_POSIX_SOURCE_PATH = re.compile(
    r"(?<![:/])(/[^<>:\"|?*\r\n]*?\.(?:txt|md))",
    re.IGNORECASE,
)
_CANCEL_REMINDER = re.compile(r"^\s*\u53d6\u6d88\u63d0\u9192\s*([1-9]\d*)\s*$")
_DELETE_ALL_REMINDERS = re.compile(
    r"^\s*(?:\u8bf7|\u5e2e\u6211|\u8bf7\u5e2e\u6211)?\s*"
    r"(?:\u5220\u9664\u6240\u6709\u63d0\u9192|\u5220\u9664\u5168\u90e8\u63d0\u9192|\u6e05\u7a7a\u63d0\u9192)\s*"
    r"[!\uff01.\u3002]?\s*$"
)
_SUMMARIZE_PREFIXES = ("\u7f29\u5199", "\u603b\u7ed3")
_DRAFT_PREFIX = "\u8349\u62df"
_TONE_CUES = ("\u8c03\u6574\u8bed\u6c14", "\u8bed\u6c14\u8c03\u6574")
_REMINDER_TIME_CUE = re.compile(
    r"(?:\d+\s*(?:\u5206\u949f|\u5c0f\u65f6|\u5929)\u540e|(?:\u4eca\u5929|\u660e\u5929|\u540e\u5929).*(?:\d{1,2}(?::\d{2})?|\u70b9)|\u6bcf\u5468[\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u65e5\u5929].*(?:\d{1,2}(?::\d{2})?|\u70b9))"
)
_REMINDER_SCOPE_ALIASES = {
    "past_events": "overdue",
    "expired": "overdue",
    "today": "next_7_days",
}
_VALID_TEXT_TONES = {"formal", "casual"}
_TODO_PRIORITY_ALIASES = {"高": "high", "高优先级": "high", "中": "medium", "普通": "medium", "低": "low", "低优先级": "low"}
_CANCEL_SCHEDULE = re.compile(r"^\s*取消日程\s*([1-9]\d*)\s*$")
_CANCEL_SCHEDULE_TITLE = re.compile(r"^\s*取消日程\s+(.+?)\s*$")
_KNOWLEDGE_WRAPPER = re.compile(r"^\s*知识库(?:里|中)?(?:有|的)?\s*(.+?)(?:吗|[？?])?\s*$")
_WEEKLY_DAYS = re.compile(r"每周([一二三四五六日天]+)")
_WEEKDAY_MAP = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}


@dataclass(frozen=True)
class NormalizationResult:
    """Canonical arguments and the deterministic rules that changed them."""

    arguments: dict[str, JsonValue]
    applied_rules: list[str]


def _unique_source_path(request_text: str) -> str | None:
    paths = [match.group(1).strip() for match in _WINDOWS_SOURCE_PATH.finditer(request_text)]
    paths.extend(match.group(1).strip() for match in _POSIX_SOURCE_PATH.finditer(request_text))
    unique_paths = list(dict.fromkeys(paths))
    return unique_paths[0] if len(unique_paths) == 1 else None


def normalize_arguments(
    *,
    intent: str,
    arguments: Mapping[str, JsonValue],
    request_text: str,
) -> NormalizationResult:
    """Return repaired arguments without mutating model output or request text.

    Every repair is deliberately constrained to an intent and a request pattern.  The
    function never infers missing values from context beyond a single literal source
    path present in the request.
    """

    normalized = dict(arguments)
    applied_rules: list[str] = []

    if intent == "knowledge_query" and "question" in normalized:
        if "query" not in normalized:
            normalized["query"] = normalized["question"]
            applied_rules.append("knowledge_query.question_to_query")
        else:
            applied_rules.append("knowledge_query.drop_question_alias")
        del normalized["question"]

    if intent == "knowledge_query":
        wrapper = _KNOWLEDGE_WRAPPER.fullmatch(request_text)
        if wrapper is not None:
            query = wrapper.group(1).strip()
            if query and normalized.get("query") != query:
                normalized["query"] = query
                applied_rules.append("knowledge_query.strip_knowledge_wrapper")

    if intent == "file_open" and "keyword" in normalized:
        if "query" not in normalized:
            normalized["query"] = normalized["keyword"]
            applied_rules.append("file_open.keyword_to_query")
        else:
            applied_rules.append("file_open.drop_keyword_alias")
        del normalized["keyword"]

    elif intent == "meeting_process":
        source_path = _unique_source_path(request_text)
        if source_path is not None and normalized.get("source_path") != source_path:
            normalized["source_path"] = source_path
            applied_rules.append("meeting_process.source_path_from_request")

    elif intent == "reminder_create":
        cancel_match = _CANCEL_REMINDER.fullmatch(request_text)
        if cancel_match is not None:
            normalized["action"] = "cancel"
            normalized["id"] = int(cancel_match.group(1))
            applied_rules.append("reminder_create.cancel_with_id_from_request")
        elif _DELETE_ALL_REMINDERS.fullmatch(request_text) is not None:
            normalized["action"] = "delete_all"
            applied_rules.append("reminder_create.delete_all_from_request")
        elif normalized.get("action") == "create":
            if "scope" in normalized:
                del normalized["scope"]
                applied_rules.append("reminder_create.drop_scope_for_create")
            if _REMINDER_TIME_CUE.search(request_text):
                normalized["when"] = request_text
                applied_rules.append("reminder_create.when_from_request")
        elif normalized.get("action") == "query":
            scope = normalized.get("scope")
            replacement = _REMINDER_SCOPE_ALIASES.get(scope) if isinstance(scope, str) else None
            if replacement is not None:
                normalized["scope"] = replacement
                applied_rules.append(f"reminder_create.{scope}_to_{replacement}")

    elif intent == "todo_manage":
        priority = normalized.get("priority")
        if isinstance(priority, str) and priority in _TODO_PRIORITY_ALIASES:
            normalized["priority"] = _TODO_PRIORITY_ALIASES[priority]
            applied_rules.append("todo_manage.priority_to_canonical")
        if (
            normalized.get("action") in {"complete", "delete", "update"}
            and "id" not in normalized
            and isinstance(normalized.get("title_query"), str)
        ):
            normalized["action"] = "query"
            applied_rules.append("todo_manage.title_mutation_to_query")

    elif intent == "schedule_manage":
        cancel_match = _CANCEL_SCHEDULE.fullmatch(request_text)
        if cancel_match is not None:
            normalized["action"] = "cancel"
            normalized["id"] = int(cancel_match.group(1))
            applied_rules.append("schedule_manage.cancel_with_id_from_request")
        elif (title_match := _CANCEL_SCHEDULE_TITLE.fullmatch(request_text)) is not None:
            title = title_match.group(1).strip()
            if title and not title.isdigit():
                normalized["action"] = "query"
                normalized["title_query"] = title
                normalized.pop("id", None)
                normalized.pop("title", None)
                applied_rules.append("schedule_manage.cancel_title_to_query")
        elif normalized.get("action") == "create" and "每周" in request_text:
            if normalized.get("recurrence") != "weekly":
                normalized["recurrence"] = "weekly"
                applied_rules.append("schedule_manage.weekly_recurrence_from_request")
            weekdays = _WEEKLY_DAYS.search(request_text)
            if weekdays is not None:
                values = list(dict.fromkeys(_WEEKDAY_MAP[item] for item in weekdays.group(1)))
                if normalized.get("weekdays") != values:
                    normalized["weekdays"] = values
                    applied_rules.append("schedule_manage.weekdays_from_request")
        elif normalized.get("action") == "query" and "range" not in normalized:
            for marker, range_value in (("今天", "today"), ("明天", "tomorrow"), ("下周", "next_week"), ("本周", "this_week")):
                if marker in request_text:
                    normalized["range"] = range_value
                    applied_rules.append(f"schedule_manage.{marker}_to_{range_value}")
                    break

    elif intent == "text_polish":
        operation = normalized.get("operation")
        stripped = request_text.lstrip()
        if stripped.startswith(_SUMMARIZE_PREFIXES) and operation in {None, "polish"}:
            normalized["operation"] = "summarize"
            applied_rules.append("text_polish.summarize_from_request")
        elif stripped.startswith(_DRAFT_PREFIX):
            normalized["operation"] = "draft"
            applied_rules.append("text_polish.draft_from_request")
        elif any(cue in request_text for cue in _TONE_CUES):
            normalized["operation"] = "tone_adjust"
            if normalized.get("tone") not in _VALID_TEXT_TONES:
                normalized.pop("tone", None)
            applied_rules.append("text_polish.tone_adjust_from_request")
        elif operation in {"rewrite", "clarify"}:
            normalized["operation"] = "polish"
            applied_rules.append("text_polish.operation_to_polish")

    return NormalizationResult(arguments=normalized, applied_rules=applied_rules)


__all__ = ["NormalizationResult", "normalize_arguments"]
