"""Authorized file indexing, candidate selection, and platform opening."""

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from pydantic import JsonValue

from agent_platform.core.errors import PermissionDeniedError
from agent_platform.core.interfaces import FileOpener, Tool
from agent_platform.models import DataLevel, RiskLevel, ToolMetadata, ToolReceipt

_CJK_RUN = re.compile(r"[\u4e00-\u9fff]")


def _is_subsequence(term: str, target: str) -> bool:
    cursor = iter(target)
    return all(character in cursor for character in term)


class FileSearchTool(Tool):
    def __init__(self, roots: list[Path], opener: FileOpener) -> None:
        self._roots = tuple(root.resolve() for root in roots)
        for root in self._roots:
            root.mkdir(parents=True, exist_ok=True)
        self._opener = opener
        self._index: dict[Path, tuple[int, float]] = {}

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="file_open",
            description="Search authorized files and open a confirmed candidate",
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "minLength": 1},
                    "selected_path": {"type": "string", "minLength": 1},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            risk_level=RiskLevel.R1,
            data_level=DataLevel.D1,
            timeout_seconds=5,
        )

    def idempotency_key(self, arguments: dict[str, JsonValue]) -> str:
        encoded = json.dumps(arguments, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return f"file_open:{hashlib.sha256(encoded).hexdigest()}"

    def build_index(self) -> int:
        current: dict[Path, tuple[int, float]] = {}
        for root in self._roots:
            for path in root.rglob("*"):
                if path.is_file():
                    try:
                        stat = path.stat()
                    except OSError:
                        continue
                    current[path.resolve()] = (stat.st_size, stat.st_mtime)
        self._index = current
        return len(current)

    def search(self, query: str, limit: int = 20) -> list[dict[str, JsonValue]]:
        self.build_index()
        terms = [term.casefold() for term in re.split(r"[\s,，:：.、;;]+", query) if term]
        scored: list[tuple[int, Path]] = []
        for path in self._index:
            searchable = f"{path.stem} {path.suffix.lstrip('.')} {path.parent.name}".casefold()
            name = path.name.casefold()
            score = 0
            for term in terms:
                if term in searchable:
                    score += 3 if term in name else 1
                elif (
                    len(term) >= 2
                    and _CJK_RUN.search(term)
                    and _is_subsequence(term, name)
                ):
                    # Spoken-Chinese queries ("待办清单") must still match real
                    # filenames ("待办任务清单_本周.txt") that insert extra words.
                    score += 2
            if score or query.casefold() in name:
                scored.append((score or 1, path))
        scored.sort(key=lambda item: (-item[0], -self._index[item[1]][1], item[1].name.casefold()))
        return [self._candidate(path) for _, path in scored[:limit]]

    def _candidate(self, path: Path) -> dict[str, JsonValue]:
        root = next(root for root in self._roots if path.is_relative_to(root))
        return {
            "name": path.name,
            "path": str(path),
            "path_summary": str(path.relative_to(root)),
            "modified_at": datetime.fromtimestamp(self._index[path][1]).isoformat(),
        }

    def _authorized(self, path: Path) -> bool:
        resolved = path.resolve()
        return resolved in self._index and any(resolved.is_relative_to(root) for root in self._roots)

    async def execute(self, arguments: dict[str, JsonValue]) -> ToolReceipt:
        query = str(arguments["query"])
        selected = arguments.get("selected_path")
        if selected:
            self.build_index()
            path = Path(str(selected)).resolve()
            if not self._authorized(path):
                raise PermissionDeniedError("Selected file is outside the authorized index")
            platform_receipt = await self._opener.open(path)
            return ToolReceipt(
                tool_name=self.metadata.name,
                actual_arguments=arguments,
                success=True,
                output_summary=f"文件处理完成：{path.name}",
                output=platform_receipt,
            )

        candidates = self.search(query)
        if not candidates:
            return ToolReceipt(
                tool_name=self.metadata.name,
                actual_arguments=arguments,
                success=True,
                output_summary="未找到匹配文件",
                output={"candidates": [], "requires_confirmation": False},
                next_actions=["修改关键词后重试"],
            )
        if len(candidates) > 1:
            return ToolReceipt(
                tool_name=self.metadata.name,
                actual_arguments=arguments,
                success=True,
                output_summary=f"找到 {len(candidates)} 个候选文件，请确认",
                output={"candidates": candidates, "requires_confirmation": True},
                next_actions=["选择 selected_path 后确认"],
            )
        path = Path(str(candidates[0]["path"]))
        platform_receipt = await self._opener.open(path)
        return ToolReceipt(
            tool_name=self.metadata.name,
            actual_arguments=arguments,
            success=True,
            output_summary=f"唯一候选：{path.name}",
            output={**platform_receipt, "candidates": candidates, "requires_confirmation": False},
        )


__all__ = ["FileSearchTool"]

