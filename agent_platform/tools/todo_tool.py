"""Local, ID-addressed todo management with deterministic persistence."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from pydantic import JsonValue

from agent_platform.core.interfaces import Tool
from agent_platform.models import DataLevel, RiskLevel, ToolMetadata, ToolReceipt
from agent_platform.tools.reminder_tool import ChineseTimeParser


_MUTABLE_FIELDS = ("title", "description", "priority", "tags", "status", "due_text")


class TodoTool(Tool):
    """Persist personal todos; state changes are always addressed by a row ID."""

    def __init__(self, database_path: Path, timezone: str = "Asia/Shanghai") -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(database_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA busy_timeout=5000")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._lock = asyncio.Lock()
        self._time_parser = ChineseTimeParser(timezone)
        self._connection.execute(
            """CREATE TABLE IF NOT EXISTS todos(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                priority TEXT NOT NULL DEFAULT 'medium' CHECK(priority IN ('high', 'medium', 'low')),
                tags TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'in_progress', 'completed')),
                due_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT
            )"""
        )
        self._connection.execute("CREATE INDEX IF NOT EXISTS idx_todos_status_due ON todos(status, due_at)")
        self._connection.commit()

    @property
    def metadata(self) -> ToolMetadata:
        update_requirements = [{"required": [name]} for name in _MUTABLE_FIELDS]
        return ToolMetadata(
            name="todo_manage",
            description="Create, query, update, complete, and delete local todos by ID",
            parameters_schema={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["create", "query", "update", "complete", "delete"]},
                    "id": {"type": "integer", "minimum": 1},
                    "title": {"type": "string", "minLength": 1, "maxLength": 500},
                    "description": {"type": "string", "maxLength": 5000},
                    "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                    "tags": {"type": "array", "items": {"type": "string", "minLength": 1, "maxLength": 80}, "maxItems": 20},
                    "status": {"type": "string", "enum": ["pending", "in_progress", "completed", "all"]},
                    "tag": {"type": "string", "minLength": 1, "maxLength": 80},
                    "due_text": {"type": "string", "maxLength": 200},
                    "title_query": {"type": "string", "minLength": 1, "maxLength": 500},
                    "due_from": {"type": "string", "format": "date-time"},
                    "due_to": {"type": "string", "format": "date-time"},
                },
                "required": ["action"],
                "allOf": [
                    {
                        "if": {"properties": {"action": {"const": "create"}}, "required": ["action"]},
                        "then": {"required": ["title"]},
                    },
                    {
                        "if": {"properties": {"action": {"const": "update"}}, "required": ["action"]},
                        "then": {"allOf": [{"required": ["id"]}, {"anyOf": update_requirements}]},
                    },
                    {
                        "if": {"properties": {"action": {"const": "complete"}}, "required": ["action"]},
                        "then": {"required": ["id"]},
                    },
                    {
                        "if": {"properties": {"action": {"const": "delete"}}, "required": ["action"]},
                        "then": {"required": ["id"]},
                    },
                ],
                "additionalProperties": False,
            },
            risk_level=RiskLevel.R1,
            data_level=DataLevel.D1,
            timeout_seconds=5,
        )

    def idempotency_key(self, arguments: dict[str, JsonValue]) -> str:
        if arguments.get("action") == "query":
            # Query results are time-sensitive and must not reuse a stale receipt.
            return f"todo:query:{datetime.now(UTC).isoformat()}"
        value = json.dumps(arguments, ensure_ascii=False, sort_keys=True)
        return f"todo:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"

    async def execute(self, arguments: dict[str, JsonValue]) -> ToolReceipt:
        action = str(arguments["action"])
        if action == "create":
            return await self._create(arguments)
        if action == "query":
            return await self._query(arguments)
        if action == "update":
            return await self._update(arguments)
        if action == "complete":
            return await self._complete(int(arguments["id"]), arguments)
        if action == "delete":
            return await self._delete(int(arguments["id"]), arguments)
        raise ValueError(f"Unsupported todo action: {action}")

    def _due_at(self, arguments: dict[str, JsonValue]) -> str | None:
        due_text = str(arguments.get("due_text", "")).strip()
        if not due_text:
            return None
        due_at, repeat = self._time_parser.parse(due_text)
        if repeat is not None:
            raise ValueError("待办截止时间不支持重复规则，请提供单次时间")
        return due_at.isoformat()

    def _time_error(self, arguments: dict[str, JsonValue], message: str) -> ToolReceipt:
        return ToolReceipt(
            tool_name=self.metadata.name,
            actual_arguments=arguments,
            success=True,
            output_summary=message,
            output={"requires_confirmation": True, "confirmation_type": "missing_fields", "fields": ["due_text"], "message": message},
            next_actions=["补充明确的截止时间后重试"],
        )

    @staticmethod
    def _item(row: sqlite3.Row) -> dict[str, JsonValue]:
        return {
            "id": int(row["id"]),
            "title": str(row["title"]),
            "description": str(row["description"]),
            "priority": str(row["priority"]),
            "tags": json.loads(str(row["tags"])),
            "status": str(row["status"]),
            "due_at": str(row["due_at"]) if row["due_at"] is not None else None,
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "completed_at": str(row["completed_at"]) if row["completed_at"] is not None else None,
        }

    async def _create(self, arguments: dict[str, JsonValue]) -> ToolReceipt:
        now = datetime.now(UTC).isoformat()
        try:
            due_at = self._due_at(arguments)
        except ValueError as exc:
            return self._time_error(arguments, str(exc))
        tags = list(dict.fromkeys(str(tag).strip() for tag in arguments.get("tags", []) if str(tag).strip()))
        async with self._lock:
            cursor = self._connection.execute(
                """INSERT INTO todos(title, description, priority, tags, status, due_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)""",
                (
                    str(arguments["title"]).strip(),
                    str(arguments.get("description", "")).strip(),
                    str(arguments.get("priority", "medium")),
                    json.dumps(tags, ensure_ascii=False),
                    due_at,
                    now,
                    now,
                ),
            )
            self._connection.commit()
            row = self._connection.execute("SELECT * FROM todos WHERE id = ?", (cursor.lastrowid,)).fetchone()
        assert row is not None
        item = self._item(row)
        return ToolReceipt(
            tool_name=self.metadata.name,
            actual_arguments=arguments,
            success=True,
            output_summary=f"已创建待办 {item['id']}：{item['title']}",
            output={"item": item},
        )

    async def _query(self, arguments: dict[str, JsonValue]) -> ToolReceipt:
        clauses: list[str] = []
        parameters: list[object] = []
        status = str(arguments.get("status", ""))
        if status and status != "all":
            clauses.append("status = ?")
            parameters.append(status)
        elif not status:
            clauses.append("status IN ('pending', 'in_progress')")
        priority = arguments.get("priority")
        if priority is not None:
            clauses.append("priority = ?")
            parameters.append(str(priority))
        title_query = str(arguments.get("title_query", "")).strip()
        if title_query:
            clauses.append("title LIKE ?")
            parameters.append(f"%{title_query}%")
        tag = str(arguments.get("tag", "")).strip()
        if tag:
            clauses.append("tags LIKE ?")
            parameters.append(f'%"{tag}"%')
        for field, operator in (("due_from", ">="), ("due_to", "<=")):
            value = arguments.get(field)
            if value is not None:
                clauses.append(f"due_at {operator} ?")
                parameters.append(str(value))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        async with self._lock:
            rows = self._connection.execute(
                f"SELECT * FROM todos {where} ORDER BY CASE WHEN due_at IS NULL THEN 1 ELSE 0 END, due_at, id",
                tuple(parameters),
            ).fetchall()
        items = [self._item(row) for row in rows]
        return ToolReceipt(
            tool_name=self.metadata.name,
            actual_arguments=arguments,
            success=True,
            output_summary=f"查询到 {len(items)} 条待办",
            output={"items": items},
        )

    async def _update(self, arguments: dict[str, JsonValue]) -> ToolReceipt:
        todo_id = int(arguments["id"])
        fields: list[str] = []
        parameters: list[object] = []
        for name in ("title", "description", "priority", "status"):
            if name in arguments:
                fields.append(f"{name} = ?")
                parameters.append(str(arguments[name]).strip())
        if "tags" in arguments:
            tags = list(dict.fromkeys(str(tag).strip() for tag in arguments["tags"] if str(tag).strip()))
            fields.append("tags = ?")
            parameters.append(json.dumps(tags, ensure_ascii=False))
        if "due_text" in arguments:
            try:
                due_at = self._due_at(arguments)
            except ValueError as exc:
                return self._time_error(arguments, str(exc))
            fields.append("due_at = ?")
            parameters.append(due_at)
        fields.append("updated_at = ?")
        parameters.append(datetime.now(UTC).isoformat())
        parameters.append(todo_id)
        async with self._lock:
            cursor = self._connection.execute(f"UPDATE todos SET {', '.join(fields)} WHERE id = ?", tuple(parameters))
            self._connection.commit()
            row = self._connection.execute("SELECT * FROM todos WHERE id = ?", (todo_id,)).fetchone()
        if cursor.rowcount != 1 or row is None:
            return self._not_found(arguments, todo_id)
        item = self._item(row)
        return ToolReceipt(
            tool_name=self.metadata.name,
            actual_arguments=arguments,
            success=True,
            output_summary=f"已更新待办 {todo_id}",
            output={"item": item},
        )

    async def _complete(self, todo_id: int, arguments: dict[str, JsonValue]) -> ToolReceipt:
        now = datetime.now(UTC).isoformat()
        async with self._lock:
            cursor = self._connection.execute(
                "UPDATE todos SET status = 'completed', completed_at = ?, updated_at = ? WHERE id = ?",
                (now, now, todo_id),
            )
            self._connection.commit()
            row = self._connection.execute("SELECT * FROM todos WHERE id = ?", (todo_id,)).fetchone()
        if cursor.rowcount != 1 or row is None:
            return self._not_found(arguments, todo_id)
        return ToolReceipt(
            tool_name=self.metadata.name,
            actual_arguments=arguments,
            success=True,
            output_summary=f"待办 {todo_id} 已完成",
            output={"item": self._item(row)},
        )

    async def _delete(self, todo_id: int, arguments: dict[str, JsonValue]) -> ToolReceipt:
        async with self._lock:
            row = self._connection.execute("SELECT * FROM todos WHERE id = ?", (todo_id,)).fetchone()
            if row is None:
                return self._not_found(arguments, todo_id)
            item = self._item(row)
            self._connection.execute("DELETE FROM todos WHERE id = ?", (todo_id,))
            self._connection.commit()
        return ToolReceipt(
            tool_name=self.metadata.name,
            actual_arguments=arguments,
            success=True,
            output_summary=f"已删除待办 {todo_id}",
            output={"deleted": item},
        )

    def _not_found(self, arguments: dict[str, JsonValue], todo_id: int) -> ToolReceipt:
        return ToolReceipt(
            tool_name=self.metadata.name,
            actual_arguments=arguments,
            success=True,
            output_summary=f"未找到待办 {todo_id}",
            output={"updated": False, "id": todo_id},
        )

    def close(self) -> None:
        self._connection.close()


__all__ = ["TodoTool"]
