"""Deterministic Chinese-first model adapter used by tests and offline demos."""

import re
from collections.abc import Sequence

from jsonschema import Draft202012Validator
from pydantic import JsonValue

from agent_platform.core.interfaces import ModelAdapter
from agent_platform.models import ModelMessage, is_argument_extraction_schema, is_intent_classification_schema


class MockModelAdapter(ModelAdapter):
    """Map supported Chinese requests to the five MVP tool schemas."""

    _path_pattern = re.compile(r"(?:[A-Za-z]:\\[^\r\n\"']+|/[^\r\n\"']+\.(?:txt|md))", re.IGNORECASE)

    @staticmethod
    def _todo_result(text: str) -> dict[str, JsonValue]:
        """Map only explicit ID mutations; title references remain a safe query."""

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
            title = re.sub(r"^.*?(?:添加|新增|创建|新建)待办(?:事项)?[：:\s]*", "", text).strip()
            arguments: dict[str, JsonValue] = {"action": "create", "title": title or text}
            if any(word in text for word in ("高优先级", "优先级高", "紧急")):
                arguments["priority"] = "high"
            elif any(word in text for word in ("低优先级", "不着急")):
                arguments["priority"] = "low"
            if re.search(r"\d+\s*(?:分钟|小时|天)后", text) or any(word in text for word in ("今天", "明天", "后天")):
                arguments["due_text"] = text
            return arguments

        query = re.sub(r"^.*?(?:查看|查询|列出|有哪些)待办(?:事项)?[：:\s]*", "", text).strip()
        return {"action": "query", **({"title_query": query} if query else {})}

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
            title = re.sub(r"^.*?(?:添加|新增|创建|新建|安排)日程[：:\s]*", "", text).strip()
            arguments: dict[str, JsonValue] = {"action": "create", "title": title or text, "start_text": text}
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
        elif "下周" in text:
            range_value = "next_week"
        query = re.sub(r"^.*?(?:查看|查询|有什么|有哪些)日程[：:\s]*", "", text).strip()
        return {"action": "query", "range": range_value, **({"title_query": query} if query else {})}

    async def generate(
        self,
        messages: Sequence[ModelMessage],
        response_schema: dict[str, JsonValue],
        max_tokens: int = 512,
    ) -> dict[str, JsonValue]:
        del max_tokens
        text = messages[-1].content.strip()
        if "text" in response_schema.get("properties", {}) and response_schema.get("required") == ["text"]:
            result = {"text": text}
            Draft202012Validator(response_schema).validate(result)
            return result

        file_command = re.match(r"^(?:请|帮我|请帮我)?(?:打开|查找|找一下|找)", text)
        if file_command:
            query = re.sub(r"^(请|帮我|请帮我)?(?:打开|查找|找一下|找)[：:\s]*", "", text)
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
        elif "日程" in text or re.search(r"(?:今天|明天|后天).*(?:有什么|有哪些).*安排", text):
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
            if any(phrase in text for phrase in ("删除所有提醒", "删除全部提醒", "清空提醒", "删除全部待办")):
                action = "delete_all"
            elif "取消" in text:
                action = "cancel"
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
                "arguments": {"action": action, "text": text},
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
            query = re.sub(r"^(请|帮我|请帮我)?(?:打开|查找|找一下|找)[：:\s]*", "", text)
            result = {
                "intent": "file_open",
                "arguments": {"query": query or text},
                "missing_fields": [],
                "confidence": 0.97,
            }
        else:
            query = re.sub(r"^(请|帮我)?(?:查询|查一下|告诉我)[：:\s]*", "", text)
            result = {
                "intent": "knowledge_query",
                "arguments": {"query": query or text},
                "missing_fields": [],
                "confidence": 0.82,
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
