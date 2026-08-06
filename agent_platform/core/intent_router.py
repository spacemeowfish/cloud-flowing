"""Conservative intent-only routing for unambiguous Chinese request anchors."""

from __future__ import annotations

import re
from dataclasses import dataclass


_ABSOLUTE_TEXT_PATH = re.compile(
    r"(?:[A-Za-z]:\\[^\r\n\"']+\.(?:txt|md)|/(?:[^\s/]+/)*[^\s]+\.(?:txt|md))",
    re.IGNORECASE,
)
_RELATIVE_TIME = re.compile(r"\d+\s*(?:分钟|小时|天)后")


@dataclass(frozen=True)
class PreRouteDecision:
    intent: str
    rule: str


def pre_route_intent(text: str) -> PreRouteDecision | None:
    """Return an intent only when product semantics have a high-confidence anchor."""

    normalized = text.strip()
    if _ABSOLUTE_TEXT_PATH.search(normalized) and any(
        marker in normalized for marker in ("会议纪要", "会议记录", "整理会议", "会议文稿", "会议文稿在")
    ):
        return PreRouteDecision("meeting_process", "meeting_text_path")

    if re.match(r"^(?:请|帮我|请帮我)?(?:润色|改写|草拟|缩写|总结(?:这段)?|调整语气|语气调整)", normalized):
        return PreRouteDecision("text_polish", "text_operation_prefix")

    if "提醒" in normalized:
        return PreRouteDecision("reminder_create", "explicit_reminder")
    if re.search(r"(?:查看|查询).*(?:未来|过期|7天).*待办", normalized):
        return PreRouteDecision("reminder_create", "reminder_scope_query")
    if _RELATIVE_TIME.search(normalized) and "待办" in normalized:
        return PreRouteDecision("reminder_create", "relative_time_priority")

    if "日程" in normalized or re.search(r"(?:今天|明天|后天).*(?:有什么|有哪些).*安排", normalized):
        return PreRouteDecision("schedule_manage", "explicit_schedule")
    if any(marker in normalized for marker in ("待办", "待处理", "标记为完成")):
        return PreRouteDecision("todo_manage", "explicit_todo")

    if re.match(r"^(?:请|帮我|请帮我)?(?:打开|查找|找一下|找)", normalized) or any(
        marker in normalized for marker in ("查找文件", "找文件", "文件在哪")
    ):
        return PreRouteDecision("file_open", "explicit_file_action")

    if (
        re.match(r"^(?:请|帮我|请帮我)?(?:查询|查一下|告诉我|如何)", normalized)
        or "知识库" in normalized
        or normalized.endswith("是什么")
    ):
        return PreRouteDecision("knowledge_query", "knowledge_question")
    return None


__all__ = ["PreRouteDecision", "pre_route_intent"]
