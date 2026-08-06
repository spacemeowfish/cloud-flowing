"""Local document ingestion, vector retrieval, short answers, and citations."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import JsonValue

from agent_platform.core.data_classification import DataClassificationService
from agent_platform.core.errors import PermissionDeniedError
from agent_platform.core.interfaces import Tool
from agent_platform.models import DataLevel, RiskLevel, ToolMetadata, ToolReceipt
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

    def sync_documents(self) -> int:
        updated = 0
        for root in self._roots:
            for path in root.rglob("*"):
                if path.is_file() and path.suffix.casefold() in {".txt", ".md", ".docx"}:
                    updated += int(self.ingest_document(path))
        return updated

    def ingest_document(self, path: Path, *, force: bool = False) -> bool:
        """Index one authorized document; return whether the stored index changed."""

        resolved = path.resolve()
        if not resolved.is_file() or resolved.suffix.casefold() not in {".txt", ".md", ".docx"}:
            raise ValueError(f"不支持的文档：{path.name}")
        if not any(resolved.is_relative_to(root) for root in self._roots):
            raise PermissionDeniedError(f"文档不在知识库白名单中：{path}")
        if any(marker in resolved.name.casefold() for marker in ("password", "secret", "key")):
            raise PermissionDeniedError(f"文档名称触发敏感规则：{path.name}")
        mtime = resolved.stat().st_mtime
        if not force and self._store.indexed_mtime(resolved) == mtime:
            return False
        text = self._parser.parse(resolved)
        classified = self._classifier.classify(text)
        chunks = chunk_text(classified.redacted_text)
        if not chunks:
            raise ValueError(f"文档没有可索引内容：{path.name}")
        scope = extract_document_scope(classified.redacted_text, resolved.suffix)
        self._store.replace_document(resolved, mtime, chunks, scope=scope)
        return True

    async def execute(self, arguments: dict[str, JsonValue]) -> ToolReceipt:
        query = str(arguments["query"])
        self.sync_documents()
        normalized_query = "".join(query.casefold().split())
        query_bigrams = {
            normalized_query[index : index + 2] for index in range(max(0, len(normalized_query) - 1))
        }
        minimum_matches = 1 if len(normalized_query) <= 5 else 2
        hits = []
        for hit in self._store.search(query, self._top_k):
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
        best = hits[0]
        answer_text = best.text[:500].strip()
        answer = f"根据《{best.document}》分块 {best.position + 1}：{answer_text}"
        sources = [
            {
                "file": hit.document,
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
