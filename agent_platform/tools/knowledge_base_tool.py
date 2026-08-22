"""Local document ingestion, vector retrieval, short answers, and citations."""

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from pydantic import JsonValue

from agent_platform.core.data_classification import DataClassificationService
from agent_platform.core.errors import PermissionDeniedError
from agent_platform.core.interfaces import Tool
from agent_platform.models import DataLevel, RiskLevel, ToolContext, ToolMetadata, ToolReceipt
from agent_platform.tools.vector_store import (
    DocumentParser,
    HashingEmbedder,
    SQLiteVectorStore,
    chunk_text,
    extract_document_scope,
)


class KnowledgeBaseTool(Tool):
    def __init__(
        self,
        roots: list[Path],
        database_path: Path,
        classifier: DataClassificationService,
        *,
        dimensions: int = 256,
        top_k: int = 5,
    ) -> None:
        self._roots = tuple(root.resolve() for root in roots)
        for root in self._roots:
            root.mkdir(parents=True, exist_ok=True)
        self._parser = DocumentParser()
        self._store = SQLiteVectorStore(database_path, HashingEmbedder(dimensions))
        self._classifier = classifier
        self._top_k = top_k

    @property
    def roots(self) -> tuple[Path, ...]:
        return self._roots

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="knowledge_query",
            description="Answer from authorized local documents with source citations",
            parameters_schema={
                "type": "object",
                "properties": {"query": {"type": "string", "minLength": 1}},
                "required": ["query"],
                "additionalProperties": False,
            },
            risk_level=RiskLevel.R0,
            data_level=DataLevel.D2,
            timeout_seconds=10,
        )

    def idempotency_key(self, arguments: dict[str, JsonValue]) -> str:
        value = json.dumps(arguments, ensure_ascii=False, sort_keys=True)
        return f"knowledge:{hashlib.sha256(value.encode()).hexdigest()}"

    def sync_documents(self, owner: str) -> int:
        updated = 0
        for root in self._roots:
            for path in root.rglob("*"):
                if path.is_file() and path.suffix.casefold() in {".txt", ".md", ".docx"}:
                    updated += int(self.ingest_document(path, owner=owner))
        return updated

    def _document_paths(self) -> list[Path]:
        return sorted(
            (
                path.resolve()
                for root in self._roots
                for path in root.rglob("*")
                if path.is_file() and path.suffix.casefold() in {".txt", ".md", ".docx"}
            ),
            key=lambda path: str(path).casefold(),
        )

    @staticmethod
    def _date_from_name(name: str) -> str:
        match = re.search(r"(20\d{2})[-_/年]?(\d{2})[-_/月]?(\d{2})日?", name)
        return "-".join(match.groups()) if match else ""

    def _report_candidates(self, query: str) -> list[Path]:
        if not any(marker in query.casefold() for marker in ("周报", "项目周报", "报告")):
            return []
        candidates = [path for path in self._document_paths() if "周报" in path.stem or "报告" in path.stem]
        if "项目周报" in query:
            candidates = [path for path in candidates if "项目周报" in path.stem and self._date_from_name(path.name)]
        date_match = re.search(r"(20\d{2})\s*[年/-]?\s*(\d{1,2})\s*[月/-]?\s*(\d{1,2})?", query)
        month_match = re.search(r"(20\d{2})\s*[年/-]?\s*(\d{1,2})\s*月", query)
        if date_match and date_match.group(3):
            wanted = "-".join((date_match.group(1), date_match.group(2).zfill(2), date_match.group(3).zfill(2)))
            candidates = [path for path in candidates if self._date_from_name(path.name) == wanted]
        elif month_match:
            prefix = f"{month_match.group(1)}-{month_match.group(2).zfill(2)}"
            candidates = [path for path in candidates if self._date_from_name(path.name).startswith(prefix)]
        return candidates

    def ingest_document(self, path: Path, *, owner: str = "", force: bool = False) -> bool:
        """Index one authorized document; return whether the stored index changed."""

        resolved = path.resolve()
        if not resolved.is_file() or resolved.suffix.casefold() not in {".txt", ".md", ".docx"}:
            raise ValueError(f"不支持的文档：{path.name}")
        if not any(resolved.is_relative_to(root) for root in self._roots):
            raise PermissionDeniedError(f"文档不在知识库白名单中：{path}")
        if any(marker in resolved.name.casefold() for marker in ("password", "secret", "key")):
            raise PermissionDeniedError(f"文档名称触发敏感规则：{path.name}")
        mtime = resolved.stat().st_mtime
        if not force and self._store.indexed_mtime(resolved, owner) == mtime:
            return False
        text = self._parser.parse(resolved)
        classified = self._classifier.classify(text)
        chunks = chunk_text(classified.redacted_text)
        if not chunks:
            raise ValueError(f"文档没有可索引内容：{path.name}")
        scope = extract_document_scope(classified.redacted_text, resolved.suffix)
        self._store.replace_document(resolved, mtime, chunks, scope=scope, owner=owner)
        return True

    @staticmethod
    def _required_owner(context: ToolContext | None) -> str:
        if context is None or not context.owner:
            raise ValueError("knowledge operations require an authenticated owner context")
        return context.owner

    async def execute(self, arguments: dict[str, JsonValue], context: ToolContext | None = None) -> ToolReceipt:
        owner = self._required_owner(context)
        query = str(arguments["query"])
        self.sync_documents(owner)
        report_candidates = self._report_candidates(query)
        has_explicit_date = bool(
            re.search(r"20\d{2}\s*[年/-]?\s*\d{1,2}\s*[月/-]?\s*\d{1,2}", query)
        )
        if "项目周报" in query and has_explicit_date and not report_candidates:
            return ToolReceipt(
                tool_name=self.metadata.name,
                actual_arguments=arguments,
                success=True,
                output_summary="未找到指定日期的项目周报",
                output={"answer": "未找到指定日期的项目周报", "sources": []},
            )
        if report_candidates and "周报" in query and not has_explicit_date and len(report_candidates) > 1:
            candidates = [
                    {
                        "name": path.name,
                        "date": self._date_from_name(path.name),
                    }
                for path in report_candidates
            ]
            return ToolReceipt(
                tool_name=self.metadata.name,
                actual_arguments=arguments,
                success=True,
                output_summary="需要选择项目周报日期",
                output={
                    "type": "clarification",
                    "message": "请选择要查看的项目周报日期",
                    "candidates": candidates,
                    "sources": [],
                },
            )
        if len(report_candidates) == 1 and has_explicit_date:
            path = report_candidates[0]
            text = self._parser.parse(path).strip()
            answer = f"根据《{path.name}》（{self._date_from_name(path.name)}）：{text[:500]}"
            source = {
                "file": path.name,
                "date": self._date_from_name(path.name),
                "section": "全文",
                "snippet": " ".join(text.split())[:100],
                "updated_at": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
                "scope": extract_document_scope(text, path.suffix),
            }
            return ToolReceipt(
                tool_name=self.metadata.name,
                actual_arguments=arguments,
                success=True,
                output_summary=answer,
                output={"answer": answer, "sources": [source]},
            )
        normalized_query = "".join(query.casefold().split())
        query_bigrams = {
            normalized_query[index : index + 2] for index in range(max(0, len(normalized_query) - 1))
        }
        minimum_matches = 1 if len(normalized_query) <= 5 else 2
        hits = []
        allowed_paths = {str(path) for path in report_candidates} if report_candidates else None
        search_hits = self._store.search(query, self._top_k * 3, owner)
        if allowed_paths is not None:
            search_hits = [hit for hit in search_hits if hit.path in allowed_paths]
        for hit in search_hits[: self._top_k]:
            normalized_text = "".join(hit.text.casefold().split())
            lexical_matches = sum(token in normalized_text for token in query_bigrams)
            if hit.score > 0.02 and lexical_matches >= minimum_matches:
                hits.append(hit)
        if not hits:
            return ToolReceipt(
                tool_name=self.metadata.name,
                actual_arguments=arguments,
                success=True,
                output_summary="未找到相关信息",
                output={"answer": "未找到相关信息", "sources": []},
            )
        filename_hits = [
            hit
            for hit in hits
            if sum(token in hit.document.casefold() for token in query_bigrams) >= minimum_matches
        ]
        if filename_hits:
            hits = filename_hits
        if (
            len(hits) > 1
            and any(marker in query for marker in ("文档", "报告", "周报"))
            and hits[0].score - hits[1].score < 0.01
        ):
            return ToolReceipt(
                tool_name=self.metadata.name,
                actual_arguments=arguments,
                success=True,
                output_summary="找到多个相近文档，需要补充范围",
                output={
                    "type": "clarification",
                    "message": "找到多个相近文档，请补充文件名或日期",
                    "candidates": [{"name": hit.document, "date": self._date_from_name(hit.document)} for hit in hits[:3]],
                    "sources": [],
                },
            )
        best = hits[0]
        answer_text = best.text[:500].strip()
        answer = f"根据《{best.document}》分块 {best.position + 1}：{answer_text}"
        sources = [
            {
                "file": hit.document,
                "date": self._date_from_name(hit.document),
                "section": f"分块 {hit.position + 1}",
                "snippet": " ".join(hit.text.split())[:100],
                "updated_at": datetime.fromtimestamp(hit.mtime, UTC).isoformat(),
                "scope": hit.scope,
            }
            for hit in hits
        ]
        return ToolReceipt(
            tool_name=self.metadata.name,
            actual_arguments=arguments,
            success=True,
            output_summary=answer,
            output={"answer": answer, "sources": sources},
        )

    def close(self) -> None:
        self._store.close()


__all__ = ["KnowledgeBaseTool"]
