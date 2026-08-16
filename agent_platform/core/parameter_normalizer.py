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
_COMPLETE_REMINDER = re.compile(
    r"^\s*(?:\u8bf7|\u5e2e\u6211|\u8bf7\u5e2e\u6211)?\s*"
    r"(?:\u5b8c\u6210|\u6807\u8bb0\u4e3a\u5b8c\u6210|\u6807\u8bb0\u5b8c\u6210)\u63d0\u9192\s*"
    r"(?:ID\s*)?([1-9]\d*)\s*$"
)
_DELETE_ALL_REMINDERS = re.compile(
    r"^\s*(?:\u8bf7|\u5e2e\u6211|\u8bf7\u5e2e\u6211)?\s*"
    r"(?:\u5220\u9664\u6240\u6709\u63d0\u9192|\u5220\u9664\u5168\u90e8\u63d0\u9192|\u6e05\u7a7a\u63d0\u9192|\u6e05\u7a7a\u5168\u90e8\u63d0\u9192)\s*"
    r"[!\uff01.\u3002]?\s*$"
)
_SUMMARIZE_PREFIXES = ("\u7f29\u5199", "\u603b\u7ed3")
_DRAFT_PREFIX = "\u8349\u62df"
_TONE_CUES = ("\u8c03\u6574\u8bed\u6c14", "\u8bed\u6c14\u8c03\u6574")
_FORMAL_TONE_PREFIX = re.compile(
    r"^\s*(?:请|帮我|请帮我)?\s*调整为(?:正式|轻松)?语气"
)
_TEXT_OPERATION_PREFIX = re.compile(
    r"^\s*(?:\u8bf7|\u5e2e\u6211|\u8bf7\u5e2e\u6211)?\s*"
    r"(?:\u6da6\u8272|\u6539\u5199|\u8349\u62df|\u7f29\u5199|\u603b\u7ed3(?:\u8fd9\u6bb5)?|"
    r"\u8c03\u6574\u8bed\u6c14|\u8bed\u6c14\u8c03\u6574|\u8c03\u6574\u4e3a(?:\u6b63\u5f0f|\u8f7b\u677e)?\u8bed\u6c14)"
    r"[：:\s]*"
)
_REMINDER_TIME_CUE = re.compile(
    r"(?:[0-9\u96f6\u3007\u4e00\u4e8c\u4e24\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\u767e\u5343\u4e07\u58f9\u8d30\u53c1\u8086\u4f0d\u9646\u67d2\u634c\u7396\u62fe\u4f70\u4edf\u842c\u5104]+\s*(?:\u5206\u949f|\u5c0f\u65f6|\u5929)\u540e|(?:\u4eca\u5929|\u660e\u5929|\u540e\u5929).*(?:\d{1,2}(?::\d{2})?|\u70b9)|\u6bcf\u5468[\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u65e5\u5929\u58f9\u8d30\u53c1\u8086\u4f0d\u9646\u67d2\u634c\u7396].*(?:\d{1,2}(?::\d{2})?|\u70b9))"
)
_REMINDER_SCOPE_ALIASES = {
    "past_events": "overdue",
    "expired": "overdue",
    "today": "next_7_days",
}
_VALID_TEXT_TONES = {"formal", "casual"}
_TODO_PRIORITY_ALIASES = {"高": "high", "高优先级": "high", "中": "medium", "普通": "medium", "低": "low", "低优先级": "low"}
_TODO_STATUS_ALIASES = {
    "待处理": "pending",
    "未处理": "pending",
    "未完成": "pending",
    "未开始": "pending",
    "进行中": "in_progress",
    "处理中": "in_progress",
    "正在进行": "in_progress",
    "执行中": "in_progress",
    "已完成": "completed",
    "已办结": "completed",
    "已结束": "completed",
    "全部": "all",
    "所有": "all",
}
_TODO_UPDATE_REQUEST = re.compile(
    r"^\s*(?:请|帮我|请帮我)?(?:更新|修改|调整)待办(?:事项)?\s*"
    r"(?:ID\s*)?([1-9]\d*)\s*(?:为|改为|设置为|变更为)\s*(.+?)\s*$"
)
_TODO_MARK_REQUEST = re.compile(
    r"^\s*(?:请|帮我|请帮我)?把待办(?:事项)?\s*(?:ID\s*)?([1-9]\d*)\s*标记为\s*(.+?)\s*$"
)
_TODO_COMPLETE_REQUEST = re.compile(
    r"^\s*(?:请|帮我|请帮我)?\s*(?:完成|办结)待办(?:事项)?\s*(?:ID\s*)?([1-9]\d*)\s*$"
)
_TODO_DELETE_REQUEST = re.compile(
    r"^\s*(?:请|帮我|请帮我)?\s*(?:删除|移除)待办(?:事项)?\s*(?:ID\s*)?([1-9]\d*)\s*$"
)
_TODO_QUERY_REQUEST = re.compile(
    r"^\s*(?:请|帮我|请帮我)?\s*(?:查看|查询|列出)\s*"
    r"(全部|所有|待处理|未处理|未完成|未开始|进行中|处理中|正在进行|执行中|已完成|已办结|已结束)?"
    r"(?:的)?\s*待办(?:事项)?\s*$"
)
_CREATE_TODO_REQUEST = re.compile(
    r"^\s*(?:请|帮我|请帮我)?\s*(?:添加|新增|创建|新建)待办(?:事项)?\s*[：:\s]*\s*(.+?)\s*$"
)
_REMINDER_DELAY_TASK = re.compile(
    r"^\s*待办\s*[：:]?\s*"
    r"([0-9零〇一二两三四五六七八九十百千万壹贰叁肆伍陆柒捌玖拾佰仟萬億]+\s*(?:分钟|小时|天)后)\s*"
    r"(.+?)\s*$"
)
_CANCEL_SCHEDULE = re.compile(r"^\s*取消日程\s*([1-9]\d*)\s*$")
_CANCEL_SCHEDULE_TITLE = re.compile(r"^\s*取消日程\s+(.+?)\s*$")
_QUERY_SCHEDULE_TITLE = re.compile(r"^\s*(?:查看|查询|查找)日程(?:事项)?[：:\s]+(.+?)\s*$")
_QUERY_REMINDERS = re.compile(
    r"^\s*(?:请|帮我|请帮我)?\s*(?:查看|查询|列出)\s*"
    r"(?:(未来\s*(?:7|七)\s*天|过期|逾期)(?:的)?)?\s*提醒\s*$"
)
_WEEKLY_DAYS = re.compile(r"每周([一二三四五六日天]+)")
_WEEKDAY_MAP = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
_SCHEDULE_DATE_CUE = re.compile(
    r"(?:"
    r"[0-9零〇一二两三四五六七八九十壹贰叁肆伍陆柒捌玖拾]{4}年"
    r"[0-9零〇一二两三四五六七八九十壹贰叁肆伍陆柒捌玖拾]{1,3}月"
    r"[0-9零〇一二两三四五六七八九十壹贰叁肆伍陆柒捌玖拾]{1,3}日"
    r"|\d{1,2}月\d{1,2}日|今天|明天|后天)"
)
_SCHEDULE_TIME_CUE = re.compile(
    r"(?:"
    r"[0-9零〇一二两三四五六七八九十壹贰叁肆伍陆柒捌玖拾]{4}年"
    r"[0-9零〇一二两三四五六七八九十壹贰叁肆伍陆柒捌玖拾]{1,3}月"
    r"[0-9零〇一二两三四五六七八九十壹贰叁肆伍陆柒捌玖拾]{1,3}日"
    r"|\d{1,2}月\d{1,2}日|今天|明天|后天|每周|每月)"
    r".*(?:上午|下午|晚上)?\s*(?:\d{1,2}|[零〇一二两三四五六七八九十]+)\s*(?::\s*\d{2}|点(?:半)?)"
)
_FILE_COMMAND_WRAPPER = re.compile(
    r"^\s*(?:请|帮我|请帮我)?\s*"
    r"(?:查找并打开|打开|查找|找一下|找|查看|看看)"
    r"(?:文件)?(?:在哪)?\s*[：:,，]?\s*(.+?)\s*"
    r"(?:文件)?(?:在哪|在哪里|在哪个目录|在哪个文件夹)?\s*[?？]?\s*$"
)
_FILE_LOCATION_QUERY = re.compile(
    r"^\s*(.+?)\s*(?:文件)?(?:在哪|在哪里|在哪个目录|在哪个文件夹)\s*[?？]?\s*$"
)


def _strip_file_command(text: str) -> str:
    """Remove workbench command wording so the matcher sees the file subject."""

    wrapper = _FILE_COMMAND_WRAPPER.fullmatch(text)
    if wrapper is not None:
        return wrapper.group(1).strip() or text
    located = _FILE_LOCATION_QUERY.fullmatch(text)
    if located is not None:
        return located.group(1).strip() or text
    return text
_MEETING_ROOM_BOOKING = re.compile(
    r"^\s*(?:请|帮我|请帮我)?(?:预约|预订)\s*"
    r"([A-Za-z][A-Za-z0-9\-]{0,9}\s*)?会议室\s*$"
)
_KNOWLEDGE_WRAPPER = re.compile(
    r"^\s*(?:(?:请|帮我|请帮我)?\s*(?:查询|查一下|告诉我)\s*)?"
    r"知识库(?:里|中|中的|里面)?\s*(?:有|的)?\s*[：:,，]?\s*"
    r"(.+?)(?:吗|[？?])?\s*$"
)


@dataclass(frozen=True)
class NormalizationResult:
    """Canonical arguments and the deterministic rules that changed them."""

    arguments: dict[str, JsonValue]
    applied_rules: list[str]


def extract_text_payload(request_text: str) -> str:
    """Strip the operation command so a local text tool receives original facts."""

    payload = _TEXT_OPERATION_PREFIX.sub("", str(request_text).strip(), count=1)
    return payload.strip() or str(request_text).strip()


def deterministic_pre_route_arguments(intent: str, request_text: str) -> dict[str, JsonValue] | None:
    """Extract complete arguments only for high-confidence, literal request forms."""

    text = str(request_text).strip()
    if intent == "general_chat":
        return {"text": text}
    if intent == "knowledge_query":
        wrapper = _KNOWLEDGE_WRAPPER.fullmatch(text)
        if wrapper is not None:
            # Preserve the raw local-knowledge wording in interpretation
            # evidence. normalize_arguments records wrapper removal before
            # strict tool execution.
            query = text
        else:
            query = re.sub(
                r"^\s*(?:请|帮我|请帮我)?\s*(?:查询|查一下|告诉我)\s*[：:,，]?\s*",
                "",
                text,
                count=1,
            ).strip()
        return {"query": query or text}
    if intent == "file_open":
        return {"query": _strip_file_command(text)}
    if intent == "meeting_process":
        source_path = _unique_source_path(text)
        return {"source_path": source_path} if source_path is not None else None
    if intent == "text_polish":
        stripped = text.lstrip()
        operation = "polish"
        arguments: dict[str, JsonValue] = {"operation": operation, "text": extract_text_payload(text)}
        if stripped.startswith(_SUMMARIZE_PREFIXES):
            arguments["operation"] = "summarize"
        elif stripped.startswith(_DRAFT_PREFIX):
            arguments["operation"] = "draft"
        elif _FORMAL_TONE_PREFIX.match(text) or any(cue in text for cue in _TONE_CUES):
            arguments["operation"] = "tone_adjust"
            if "轻松" in text:
                arguments["tone"] = "casual"
            elif "正式" in text:
                arguments["tone"] = "formal"
        return arguments
    if intent == "todo_manage":
        update = _TODO_UPDATE_REQUEST.fullmatch(text) or _TODO_MARK_REQUEST.fullmatch(text)
        if update is not None:
            value = update.group(2).strip().rstrip("。！？!?，,")
            arguments = {"action": "update", "id": int(update.group(1))}
            if value in _TODO_PRIORITY_ALIASES:
                arguments["priority"] = _TODO_PRIORITY_ALIASES[value]
                return arguments
            if value in _TODO_STATUS_ALIASES and _TODO_STATUS_ALIASES[value] != "all":
                arguments["status"] = _TODO_STATUS_ALIASES[value]
                return arguments
            return None
        if (complete := _TODO_COMPLETE_REQUEST.fullmatch(text)) is not None:
            return {"action": "complete", "id": int(complete.group(1))}
        if (delete := _TODO_DELETE_REQUEST.fullmatch(text)) is not None:
            return {"action": "delete", "id": int(delete.group(1))}
        if (query := _TODO_QUERY_REQUEST.fullmatch(text)) is not None:
            label = query.group(1)
            return {"action": "query", "status": _TODO_STATUS_ALIASES.get(label, "all")}
        create = _CREATE_TODO_REQUEST.fullmatch(text)
        if create is None:
            return None
        remainder = create.group(1).strip()
        title = re.split(r"[，,]\s*(?:高|中|低|普通)?优先级", remainder, maxsplit=1)[0].strip()
        arguments = {"action": "create", "title": title or remainder}
        if any(marker in remainder for marker in ("高优先级", "优先级高", "紧急")):
            arguments["priority"] = "high"
        elif any(marker in remainder for marker in ("低优先级", "优先级低", "不着急")):
            arguments["priority"] = "low"
        elif any(marker in remainder for marker in ("中优先级", "普通优先级", "优先级中")):
            arguments["priority"] = "medium"
        return arguments
    if intent == "reminder_create":
        if _DELETE_ALL_REMINDERS.fullmatch(text) is not None:
            return {"action": "delete_all"}
        if (cancel := _CANCEL_REMINDER.fullmatch(text)) is not None:
            return {"action": "cancel", "id": int(cancel.group(1))}
        if (complete := _COMPLETE_REMINDER.fullmatch(text)) is not None:
            return {"action": "complete", "id": int(complete.group(1))}
        if (query := _QUERY_REMINDERS.fullmatch(text)) is not None:
            scope = "overdue" if query.group(1) in {"过期", "逾期"} else "next_7_days"
            return {"action": "query", "scope": scope}
        delayed = _REMINDER_DELAY_TASK.fullmatch(text)
        if delayed is not None:
            return {
                "action": "create",
                "text": delayed.group(2).strip(),
                "when": delayed.group(1).strip(),
            }
    if intent == "schedule_manage":
        booking = _MEETING_ROOM_BOOKING.fullmatch(text)
        if booking is not None:
            room = (booking.group(1) or "").strip()
            arguments: dict[str, JsonValue] = {
                "action": "create",
                "title": f"{room + ' ' if room else ''}会议室预约".replace("  ", " "),
                "start_text": text,
            }
            if room:
                arguments["location"] = room
            return arguments
        if (title_cancel := _CANCEL_SCHEDULE_TITLE.fullmatch(text)) is not None:
            title = title_cancel.group(1).strip()
            if not title.isdigit():
                return {"action": "query", "title_query": title}
        if (title_query := _QUERY_SCHEDULE_TITLE.fullmatch(text)) is not None:
            return {"action": "query", "title_query": title_query.group(1).strip()}
    return None


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

    if intent == "file_open":
        query = _strip_file_command(request_text)
        if query != request_text and normalized.get("query") != query:
            normalized["query"] = query
            applied_rules.append("file_open.strip_command_wrapper")

    elif intent == "reminder_create":
        cancel_match = _CANCEL_REMINDER.fullmatch(request_text)
        if cancel_match is not None:
            normalized["action"] = "cancel"
            normalized["id"] = int(cancel_match.group(1))
            applied_rules.append("reminder_create.cancel_with_id_from_request")
        complete_match = _COMPLETE_REMINDER.fullmatch(request_text)
        if cancel_match is None and complete_match is not None:
            normalized["action"] = "complete"
            normalized["id"] = int(complete_match.group(1))
            applied_rules.append("reminder_create.complete_with_id_from_request")
        elif cancel_match is None and _DELETE_ALL_REMINDERS.fullmatch(request_text) is not None:
            normalized["action"] = "delete_all"
            applied_rules.append("reminder_create.delete_all_from_request")
        elif cancel_match is None and complete_match is None and normalized.get("action") == "create":
            if "scope" in normalized:
                del normalized["scope"]
                applied_rules.append("reminder_create.drop_scope_for_create")
            if _REMINDER_TIME_CUE.search(request_text):
                normalized["when"] = request_text
                applied_rules.append("reminder_create.when_from_request")
        elif cancel_match is None and complete_match is None and normalized.get("action") == "query":
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
        status = normalized.get("status")
        if isinstance(status, str) and status in _TODO_STATUS_ALIASES:
            normalized["status"] = _TODO_STATUS_ALIASES[status]
            applied_rules.append("todo_manage.status_to_canonical")

        # The offline adapter intentionally stays conservative and may return a
        # query for an update sentence.  A numeric ID plus an explicit value is
        # unambiguous, so repair it before schema validation.
        update_match = _TODO_UPDATE_REQUEST.fullmatch(request_text) or _TODO_MARK_REQUEST.fullmatch(request_text)
        if update_match is not None:
            value = update_match.group(2).strip().rstrip("。！？!?，,")
            normalized["action"] = "update"
            normalized["id"] = int(update_match.group(1))
            normalized.pop("title_query", None)
            normalized.pop("title", None)
            if value in _TODO_PRIORITY_ALIASES:
                normalized["priority"] = _TODO_PRIORITY_ALIASES[value]
                applied_rules.append("todo_manage.update_priority_from_request")
            elif value in _TODO_STATUS_ALIASES and _TODO_STATUS_ALIASES[value] != "all":
                normalized["status"] = _TODO_STATUS_ALIASES[value]
                applied_rules.append("todo_manage.update_status_from_request")
        if (
            normalized.get("action") in {"complete", "delete", "update"}
            and "id" not in normalized
            and isinstance(normalized.get("title_query"), str)
        ):
            normalized["action"] = "query"
            applied_rules.append("todo_manage.title_mutation_to_query")
        elif normalized.get("action") == "query":
            # Normalize the natural-language status labels used by the local UI
            # even when the model put the whole sentence in title_query.
            status_from_request = next(
                (
                    canonical
                    for label, canonical in sorted(_TODO_STATUS_ALIASES.items(), key=lambda item: len(item[0]), reverse=True)
                    if label in request_text
                ),
                None,
            )
            if status_from_request is not None and normalized.get("status") != status_from_request:
                normalized["status"] = status_from_request
                applied_rules.append("todo_manage.status_from_request")
            title_query = normalized.get("title_query")
            if isinstance(title_query, str):
                candidate = title_query.strip()
                for prefix in ("查看", "查询", "列出", "查找", "有哪些", "待办", "待办事项"):
                    candidate = candidate.replace(prefix, "")
                for label in sorted(_TODO_STATUS_ALIASES, key=len, reverse=True):
                    candidate = candidate.replace(label, "")
                candidate = re.sub(r"^[：:，,\s]+|[：:，,\s]+$", "", candidate)
                if not candidate or candidate == request_text.strip():
                    normalized.pop("title_query", None)
                    applied_rules.append("todo_manage.drop_status_query_text")

    elif intent == "schedule_manage":
        if normalized.get("action") == "create":
            if "range_end" in normalized:
                if "end_text" not in normalized:
                    normalized["end_text"] = str(normalized["range_end"])
                    applied_rules.append("schedule_manage.range_end_to_end_text")
                else:
                    applied_rules.append("schedule_manage.drop_range_end_for_create")
                normalized.pop("range_end", None)
            current_start = str(normalized.get("start_text", "")).strip()
            request_has_date = _SCHEDULE_DATE_CUE.search(request_text) is not None
            model_has_date = _SCHEDULE_DATE_CUE.search(current_start) is not None
            if _SCHEDULE_TIME_CUE.search(request_text) and (
                not current_start
                or current_start not in request_text
                or (request_has_date and not model_has_date)
            ):
                normalized["start_text"] = request_text.strip()
                applied_rules.append("schedule_manage.start_text_from_request")
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
        elif _FORMAL_TONE_PREFIX.match(request_text):
            normalized["operation"] = "tone_adjust"
            normalized["tone"] = "casual" if "轻松" in request_text else "formal"
            applied_rules.append("text_polish.tone_adjust_from_request")
        elif any(cue in request_text for cue in _TONE_CUES):
            normalized["operation"] = "tone_adjust"
            if normalized.get("tone") not in _VALID_TEXT_TONES:
                normalized.pop("tone", None)
            applied_rules.append("text_polish.tone_adjust_from_request")
        elif operation in {"rewrite", "clarify"}:
            normalized["operation"] = "polish"
            applied_rules.append("text_polish.operation_to_polish")

    return NormalizationResult(arguments=normalized, applied_rules=applied_rules)


__all__ = ["NormalizationResult", "deterministic_pre_route_arguments", "extract_text_payload", "normalize_arguments"]
