"""Conservative intent-only routing for unambiguous Chinese request anchors."""

from __future__ import annotations

import re
from dataclasses import dataclass


_ABSOLUTE_TEXT_PATH = re.compile(
    r"(?:[A-Za-z]:\\[^\r\n\"']+\.(?:txt|md)|/(?:[^\s/]+/)*[^\s]+\.(?:txt|md))",
    re.IGNORECASE,
)
_RELATIVE_TIME = re.compile(r"\d+\s*(?:分钟|小时|天)后")
_ARITHMETIC = re.compile(
    r"^\s*(?:请)?(?:计算|算一下|算)?\s*[0-9eE.()+\-*/%\s]+\s*(?:等于多少|等于几|是多少|=|＝)?\s*[?？]?\s*$"
)
_CHINESE_ARITHMETIC = re.compile(
    r"^\s*[零一二两三四五六七八九十]+\s*(?:加|减|乘以|乘|除以|除)\s*"
    r"[零一二两三四五六七八九十]+\s*(?:等于多少|等于几|是多少)?\s*[?？]?\s*$"
)
_KNOWLEDGE_BOUND_MARKERS = (
    "知识库", "本地文档", "本地资料", "文档中", "资料中", "根据文档", "根据资料",
    "产品保修", "产品参数", "设备重启", "设备使用", "设备参数", "设备故障", "保修", "请假",
    "年假", "差旅", "入职", "报销", "安全规范", "售后", "发布流程", "会议室使用规则",
    "管理制度", "操作手册", "功能怎么用", "使用规定", "使用政策",
)
_DOCUMENT_MARKERS = ("文件", "文档", "报告", "周报", "会议记录", "会议纪要", "清单", ".txt", ".md", ".docx")
_CONTENT_MARKERS = ("中", "写了", "提到", "完成了", "进展", "内容", "总结")


@dataclass(frozen=True)
class PreRouteDecision:
    intent: str
    rule: str


def pre_route_intent(text: str) -> PreRouteDecision | None:
    """Return an intent only when product semantics have a high-confidence anchor."""

    normalized = text.strip()
    if _ARITHMETIC.fullmatch(normalized) or _CHINESE_ARITHMETIC.fullmatch(normalized):
        return PreRouteDecision("general_chat", "deterministic_arithmetic")
    if re.match(r"^(?:请)?(?:翻译|把.+翻译|将.+翻译)", normalized):
        return PreRouteDecision("general_chat", "translation_request")
    if _ABSOLUTE_TEXT_PATH.search(normalized) and any(
        marker in normalized for marker in ("会议纪要", "会议记录", "整理会议", "会议文稿", "会议文稿在")
    ):
        return PreRouteDecision("meeting_process", "meeting_text_path")

    if re.match(
        r"^(?:请|帮我|请帮我)?(?:润色|改写|草拟|缩写|总结(?:这段|以下|如下)?|调整语气|语气调整|调整为(?:正式|轻松)?语气)\s*[:：]",
        normalized,
    ):
        return PreRouteDecision("text_polish", "text_operation_prefix")

    if re.search(r"(?:提醒我|设置提醒|添加提醒|取消提醒|删除提醒|删除全部提醒|查看提醒|查询提醒)", normalized):
        return PreRouteDecision("reminder_create", "explicit_reminder")
    if re.search(r"(?:查看|查询).*(?:未来|过期|7天).*待办", normalized):
        return PreRouteDecision("reminder_create", "reminder_scope_query")
    if _RELATIVE_TIME.search(normalized) and "待办" in normalized:
        return PreRouteDecision("reminder_create", "relative_time_priority")

    if re.match(r"^(?:请|帮我|请帮我)?(?:创建|添加|取消|删除|查看|查询)(?:一个)?日程", normalized):
        return PreRouteDecision("schedule_manage", "explicit_schedule")
    if re.match(r"^(?:请|帮我|请帮我)?(?:预约|预订)", normalized) and "会议室" in normalized:
        return PreRouteDecision("schedule_manage", "meeting_room_booking")
    if re.search(r"(?:今天|明天|后天|本周|下周).*(?:有什么|有哪些).*安排", normalized):
        return PreRouteDecision("schedule_manage", "schedule_arrangement_query")
    if (
        re.search(r"(?:今天|明天|后天|本周|下周)", normalized)
        and re.search(r"(?:有没有|有什么|有哪些)", normalized)
        and re.search(r"(?:会议|安排|日程)", normalized)
        and not re.search(r"(?:会议纪要|会议记录|通知|议程)", normalized)
    ):
        # “查一下今天有没有会议”是本地日程存在性查询；排除词防止劫持
        # 会议文档类请求（纪要/记录/通知/议程）。
        return PreRouteDecision("schedule_manage", "schedule_presence_query")
    if re.match(r"^(?:请|帮我|请帮我)?(?:添加|创建|完成|删除|取消|查看|查询)(?:一个)?(?:待办|待处理)", normalized):
        return PreRouteDecision("todo_manage", "explicit_todo")

    if (
        re.match(r"^(?:请|帮我|请帮我)?(?:打开|查找|找一下|找|查看|看看)", normalized)
        and any(marker in normalized for marker in _DOCUMENT_MARKERS)
    ) or any(marker in normalized for marker in ("查找文件", "找文件", "文件在哪")):
        return PreRouteDecision("file_open", "explicit_file_action")

    if any(marker in normalized for marker in _KNOWLEDGE_BOUND_MARKERS):
        return PreRouteDecision("knowledge_query", "knowledge_question")
    if any(marker in normalized for marker in ("周报", "报告")) and any(
        marker in normalized for marker in _CONTENT_MARKERS
    ):
        return PreRouteDecision("knowledge_query", "document_content_question")
    if re.match(r"^(?:请|帮我|请帮我)?(?:查询|查一下|咨询|说明|解释)(?!.*(?:创建|预约|打开|删除|修改))", normalized) and any(
        marker in normalized for marker in _KNOWLEDGE_BOUND_MARKERS
    ):
        return PreRouteDecision("knowledge_query", "explicit_knowledge_question")
    if re.match(r"^(?:请|帮我|请帮我)?(?:为什么|什么是|谁是)", normalized) and not any(
        marker in normalized for marker in _DOCUMENT_MARKERS
    ):
        return PreRouteDecision("general_chat", "general_question")
    return None


def is_knowledge_bound_request(text: str) -> bool:
    """Whether an empty local retrieval must remain an explicit no-hit result."""

    normalized = text.strip()
    return any(marker in normalized for marker in _KNOWLEDGE_BOUND_MARKERS) or (
        any(marker in normalized for marker in ("周报", "报告"))
        and any(marker in normalized for marker in _CONTENT_MARKERS)
    )


def is_external_general_knowledge_request(text: str) -> bool:
    """Allow no-hit fallback only for questions that do not claim local state."""

    normalized = text.strip()
    if is_knowledge_bound_request(normalized):
        return False
    if any(marker in normalized for marker in (*_DOCUMENT_MARKERS, "本周会议", "本地", "日程", "提醒", "待办")):
        return False
    return bool(re.match(r"^(?:请|帮我|请帮我)?(?:什么是|为什么|如何|谁是|写出|介绍)", normalized))


__all__ = [
    "PreRouteDecision",
    "is_external_general_knowledge_request",
    "is_knowledge_bound_request",
    "pre_route_intent",
]
