"""Deterministic Chinese-first model adapter used by tests and offline demos."""

import re
from collections.abc import Sequence

from jsonschema import Draft202012Validator
from pydantic import JsonValue

from agent_platform.core.interfaces import ModelAdapter
from agent_platform.core.intent_router import is_knowledge_bound_request
from agent_platform.models import ModelMessage, is_argument_extraction_schema, is_intent_classification_schema


class MockModelAdapter(ModelAdapter):
    """Map supported Chinese requests to the five MVP tool schemas."""

    _path_pattern = re.compile(r"(?:[A-Za-z]:\\[^\r\n\"']+|/[^\r\n\"']+\.(?:txt|md))", re.IGNORECASE)
    _file_command_prefix = re.compile(
        r"^\s*(?:请|帮我|请帮我)?\s*"
        r"(?:查找并打开|打开|查找|找一下|找)"
        r"(?:文件)?(?:在哪)?\s*[：:,，]?\s*"
    )
    _schedule_clock = re.compile(
        r"(?:上午|下午|晚上)?\s*"
        r"(?:\d{1,2}|[零〇一二两三四五六七八九十壹贰叁肆伍陆柒捌玖拾]+)\s*"
        r"(?::\s*\d{2}|点(?:半)?)"
    )

    async def generate_text(
        self,
        messages: Sequence[ModelMessage],
        max_tokens: int = 512,
    ) -> str:
        del max_tokens
        return self._general_chat_result(messages[-1].content.strip())

    @classmethod
    def _file_query(cls, text: str) -> str:
        """Remove the operation wording used by the local workbench forms."""

        match = cls._file_command_prefix.match(text)
        if match is None:
            return text
        return text[match.end() :].strip() or text

    @staticmethod
    def _todo_title(text: str) -> str:
        raw = re.sub(r"^.*?(?:添加|新增|创建|新建)待办(?:事项)?[：:\s]*", "", text).strip()
        return re.split(r"[，,]\s*(?:(?:高|中|低)优先级|截止|标签)", raw, maxsplit=1)[0].strip()

    @classmethod
    def _schedule_title(cls, text: str) -> str:
        raw = re.sub(r"^.*?(?:添加|新增|创建|新建|安排)日程[：:\s]*", "", text).strip()
        title_and_time = re.split(
            r"[，,]\s*(?:结束|地点|每天重复|每日重复|每周重复|每月重复|提前)",
            raw,
            maxsplit=1,
        )[0].strip()
        clock = cls._schedule_clock.search(title_and_time)
        if clock is None:
            return title_and_time
        title = title_and_time[clock.end() :].strip(" ：:，,")
        return title or title_and_time

    @staticmethod
    def _text_result(prompt: str) -> str:
        """Return a useful deterministic text result for offline operation tests."""

        marker = "：\n" if "：\n" in prompt else ":\n"
        body = prompt.split(marker, 1)[1].strip() if marker in prompt else prompt.strip()
        if "总结以下内容" in prompt:
            # Keep the first sentence and protected facts; a real model can provide a
            # better summary when enabled, but mock mode must not echo its contract.
            sentence = re.split(r"(?<=[。！？!?])", body, maxsplit=1)[0].strip()
            return sentence or body[:120]
        if "草拟一段" in prompt:
            return f"通知：{body}"
        if "语气调整为" in prompt:
            tone_match = re.search(r"语气调整为([^风]+)风格", prompt)
            tone = tone_match.group(1).strip() if tone_match else "正式"
            return f"（{tone}）{body}"
        if "润色以下文字" in prompt:
            return re.sub(r"\s+", " ", body).strip()
        return body

    @staticmethod
    def _general_chat_result(prompt: str) -> str:
        question = prompt.rsplit("用户问题：", 1)[-1].strip()
        if "你好" in question and "翻译" in question and "英文" in question:
            return "Hello."
        return f"Mock 模式已完成通用问答流程：{question}"

    @staticmethod
    def _todo_result(text: str) -> dict[str, JsonValue]:
        """Map only explicit ID mutations; title references remain a safe query."""

        update_match = re.search(
            r"(?:更新|修改|调整)待办(?:事项)?\s*(?:ID\s*)?([1-9]\d*)\s*(?:为|改为|设置为|变更为)\s*(.+)$",
            text,
        )
        if update_match:
            value = update_match.group(2).strip().rstrip("。！？!?，,")
            if value in {"高", "高优先级"}:
                return {"action": "update", "id": int(update_match.group(1)), "priority": "high"}
            if value in {"中", "普通", "普通优先级"}:
                return {"action": "update", "id": int(update_match.group(1)), "priority": "medium"}
            if value in {"低", "低优先级"}:
                return {"action": "update", "id": int(update_match.group(1)), "priority": "low"}
            status_aliases = {"待处理": "pending", "进行中": "in_progress", "已完成": "completed"}
            if value in status_aliases:
                return {"action": "update", "id": int(update_match.group(1)), "status": status_aliases[value]}

        action_match = re.search(r"(?:删除|移除)待办(?:事项)?\s*(?:ID\s*)?([1-9]\d*)", text)
        if action_match:
            return {"action": "delete", "id": int(action_match.group(1))}
        action_match = re.search(r"(?:完成|办结)待办(?:事项)?\s*(?:ID\s*)?([1-9]\d*)", text)
        if action_match:
            return {"action": "complete", "id": int(action_match.group(1))}

        title_match = re.search(r"把\s*(.+?)\s*标记为完成", text)
        if title_match:
            return {"action": "query", "title_query": title_match.group(1).strip()}
        title_match = re.search(r"(?:完成|删除)待办(?:事项)?\s+(.+)$", text)
        if title_match:
            candidate = title_match.group(1).strip()
            if not candidate.isdigit():
                return {"action": "query", "title_query": candidate}

        if any(word in text for word in ("添加待办", "新增待办", "创建待办", "新建待办")):
            title = MockModelAdapter._todo_title(text)
            arguments: dict[str, JsonValue] = {"action": "create", "title": title or text}
            if any(word in text for word in ("高优先级", "优先级高", "紧急")):
                arguments["priority"] = "high"
            elif any(word in text for word in ("低优先级", "不着急")):
                arguments["priority"] = "low"
            elif any(word in text for word in ("中优先级", "普通优先级", "优先级中")):
                arguments["priority"] = "medium"
            if re.search(r"\d+\s*(?:分钟|小时|天)后", text) or any(word in text for word in ("今天", "明天", "后天")):
                arguments["due_text"] = text
            return arguments

        title_filter = re.search(r"[，,]\s*标题(?:包含|为|是)?\s*(.+?)\s*$", text)
        query = re.sub(r"^.*?(?:查看|查询|列出|查找|有哪些)\s*", "", text).strip()
        status_aliases = ("进行中", "处理中", "正在进行", "执行中", "已完成", "已办结", "已结束", "待处理", "未处理", "未完成", "未开始", "全部", "所有")
        status = next((value for value in status_aliases if value in query), None)
        if status is not None:
            query = query.replace(status, "")
        query = query.replace("待办事项", "").replace("待办", "").strip(" ：:，,")
        if title_filter:
            query = title_filter.group(1).strip()
        result: dict[str, JsonValue] = {"action": "query"}
        if status is not None:
            result["status"] = {
                "进行中": "in_progress", "处理中": "in_progress", "正在进行": "in_progress", "执行中": "in_progress",
                "已完成": "completed", "已办结": "completed", "已结束": "completed",
                "待处理": "pending", "未处理": "pending", "未完成": "pending", "未开始": "pending",
                "全部": "all", "所有": "all",
            }[status]
        if query:
            result["title_query"] = query
        return result

    @staticmethod
    def _schedule_result(text: str) -> dict[str, JsonValue]:
        """Keep schedule cancellation ID-addressed; title requests become a candidate query."""

        id_match = re.search(r"取消日程\s*(?:ID\s*)?([1-9]\d*)", text)
        if id_match:
            return {"action": "cancel", "id": int(id_match.group(1))}
        title_match = re.search(r"取消日程\s+(.+)$", text)
        if title_match:
            title = title_match.group(1).strip()
            if not title.isdigit():
                return {"action": "query", "title_query": title}

        if any(word in text for word in ("添加日程", "新增日程", "创建日程", "新建日程", "安排日程")):
            title = MockModelAdapter._schedule_title(text)
            arguments: dict[str, JsonValue] = {"action": "create", "title": title or text, "start_text": text}
            end_match = re.search(
                r"[，,]\s*结束(.+?)(?=[，,]\s*(?:地点|每天重复|每日重复|每周重复|每月重复|提前)|$)",
                text,
            )
            if end_match:
                arguments["end_text"] = end_match.group(1).strip()
            location_match = re.search(
                r"[，,]\s*地点(.+?)(?=[，,]\s*(?:每天重复|每日重复|每周重复|每月重复|提前)|$)",
                text,
            )
            if location_match:
                arguments["location"] = location_match.group(1).strip()
            notice_match = re.search(r"[，,]\s*提前(\d+)分钟提醒", text)
            if notice_match:
                arguments["notify_before_minutes"] = int(notice_match.group(1))
            if "每天" in text or "每日" in text:
                arguments["recurrence"] = "daily"
            elif "每周" in text:
                arguments["recurrence"] = "weekly"
                weekday_map = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
                match = re.search(r"每周([一二三四五六日天]+)", text)
                if match:
                    arguments["weekdays"] = list(dict.fromkeys(weekday_map[item] for item in match.group(1)))
            elif "每月" in text:
                arguments["recurrence"] = "monthly"
            return arguments

        range_value = "this_week"
        if "明天" in text:
            range_value = "tomorrow"
        elif "今天" in text:
            range_value = "today"
        elif "本周" in text:
            range_value = "this_week"
        elif "下周" in text:
            range_value = "next_week"
        title_filter = re.search(r"[，,]\s*标题(?:包含|为|是)?\s*(.+?)\s*$", text)
        query = re.sub(r"^.*?(?:查看|查询|有什么|有哪些)日程[：:\s]*", "", text).strip()
        if title_filter:
            query = title_filter.group(1).strip()
        elif query == text:
            query = re.sub(r"^\s*(?:今天|明天|后天|本周|下周)\s*(?:有什么|有哪些)安排[：:\s]*", "", text).strip()
        if query in {"本周", "下周", "今天", "明天", "后天"}:
            query = ""
        explicit_range = any(marker in text for marker in ("今天", "明天", "后天", "本周", "下周"))
        range_args = {"range": range_value} if explicit_range or not query else {}
        return {"action": "query", **range_args, **({"title_query": query} if query else {})}

    async def generate(
        self,
        messages: Sequence[ModelMessage],
        response_schema: dict[str, JsonValue],
        max_tokens: int = 512,
    ) -> dict[str, JsonValue]:
        del max_tokens
        text = messages[-1].content.strip()
        if "text" in response_schema.get("properties", {}) and response_schema.get("required") == ["text"]:
            result = {"text": self._text_result(text)}
            Draft202012Validator(response_schema).validate(result)
            return result
        if "answer" in response_schema.get("properties", {}) and response_schema.get("required") == ["answer"]:
            result = {"answer": self._general_chat_result(text)}
            Draft202012Validator(response_schema).validate(result)
            return result

        file_command = re.match(r"^(?:请|帮我|请帮我)?(?:打开|查找|找一下|找)", text)
        if file_command:
            query = self._file_query(text)
            result = {
                "intent": "file_open",
                "arguments": {"query": query or text},
                "missing_fields": [],
                "confidence": 0.97,
            }
        elif any(word in text for word in ("会议纪要", "会议记录", "整理会议", "会议文稿")):
            match = self._path_pattern.search(text)
            result = {
                "intent": "meeting_process",
                "arguments": {"source_path": match.group(0).strip() if match else ""},
                "missing_fields": [] if match else ["source_path"],
                "confidence": 0.96,
            }
        elif "日程" in text or re.search(r"(?:今天|明天|后天|本周|下周).*(?:有什么|有哪些).*安排", text):
            result = {
                "intent": "schedule_manage",
                "arguments": self._schedule_result(text),
                "missing_fields": [],
                "confidence": 0.95,
            }
        elif (
            ("待办" in text or "待处理" in text or "标记为完成" in text)
            and "提醒" not in text
            and not re.search(r"(?:查看|查询).*(?:未来|过期|7天).*待办", text)
            and not re.search(r"\d+\s*(?:分钟|小时|天)后", text)
        ):
            result = {
                "intent": "todo_manage",
                "arguments": self._todo_result(text),
                "missing_fields": [],
                "confidence": 0.95,
            }
        elif any(word in text for word in ("提醒", "待办", "日程")):
            action = "query" if any(word in text for word in ("查询", "查看", "未来", "过期")) else "create"
            reminder_id: int | None = None
            if any(phrase in text for phrase in ("删除所有提醒", "删除全部提醒", "清空提醒", "删除全部待办")):
                action = "delete_all"
            elif "取消" in text:
                action = "cancel"
            else:
                complete_match = re.search(r"(?:完成|标记为完成|标记完成)提醒\s*(?:ID\s*)?([1-9]\d*)", text)
                if complete_match:
                    action = "complete"
                    reminder_id = int(complete_match.group(1))
            has_specific_time = bool(
                re.search(r"\d{1,2}(?::\d{2}|点(?:半)?)", text)
                or re.search(r"\d+\s*(?:分钟|小时|天)后", text)
            )
            missing_fields = (
                ["when"]
                if action == "create"
                and any(day in text for day in ("今天", "明天", "后天"))
                and not has_specific_time
                else []
            )
            result = {
                "intent": "reminder_create",
                "arguments": {"action": action, "text": text, **({"id": reminder_id} if reminder_id is not None else {})},
                "missing_fields": missing_fields,
                "confidence": 0.95,
            }
        elif any(word in text for word in ("润色", "改写", "草拟", "缩写", "总结这段", "语气")):
            operation = "polish"
            if "草拟" in text:
                operation = "draft"
            elif any(word in text for word in ("缩写", "总结这段")):
                operation = "summarize"
            elif "语气" in text:
                operation = "tone_adjust"
            payload = re.sub(r"^(请|帮我|请帮我)?(?:润色|改写|草拟|缩写|总结这段|调整语气)[：:\s]*", "", text)
            result = {
                "intent": "text_polish",
                "arguments": {"operation": operation, "text": payload or text},
                "missing_fields": [],
                "confidence": 0.94,
            }
        elif any(word in text for word in ("打开", "查找文件", "找文件", "文件在哪")):
            query = self._file_query(text)
            result = {
                "intent": "file_open",
                "arguments": {"query": query or text},
                "missing_fields": [],
                "confidence": 0.97,
            }
        elif is_knowledge_bound_request(text):
            query = re.sub(r"^(请|帮我)?(?:查询|查一下|告诉我)[：:\s]*", "", text)
            result = {
                "intent": "knowledge_query",
                "arguments": {"query": query or text},
                "missing_fields": [],
                "confidence": 0.82,
            }
        else:
            result = {
                "intent": "general_chat",
                "arguments": {"text": text},
                "missing_fields": [],
                "confidence": 0.88,
            }

        if is_intent_classification_schema(response_schema):
            result = {"intent": result["intent"], "confidence": result["confidence"]}
        elif is_argument_extraction_schema(response_schema):
            result = {"arguments": result["arguments"], "missing_fields": result["missing_fields"]}
        Draft202012Validator(response_schema).validate(result)
        return result

    async def close(self) -> None:
        return None


if __name__ == "__main__":
    import asyncio

    from agent_platform.models import INTENT_RESPONSE_SCHEMA, MessageRole

    print(asyncio.run(MockModelAdapter().generate([ModelMessage(role=MessageRole.USER, content="提醒我明天开会")], INTENT_RESPONSE_SCHEMA)))


__all__ = ["MockModelAdapter"]
