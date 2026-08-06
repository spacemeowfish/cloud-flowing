"""Reusable bulk document import service kept independent from the CLI."""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from agent_platform.core.errors import PermissionDeniedError
from agent_platform.tools.knowledge_base_tool import KnowledgeBaseTool


@dataclass(frozen=True)
class ImportFailure:
    file: str
    error: str


@dataclass
class ImportReport:
    scanned: int = 0
    imported: int = 0
    skipped: int = 0
    failures: list[ImportFailure] = field(default_factory=list)


class KnowledgeDocumentImporter:
    def __init__(self, knowledge: KnowledgeBaseTool) -> None:
        self._knowledge = knowledge

    def import_directory(
        self,
        directory: Path,
        *,
        force: bool = False,
        progress: Callable[[str], None] | None = None,
    ) -> ImportReport:
        root = directory.resolve()
        if not root.is_dir():
            raise ValueError(f"导入目录不存在：{directory}")
        if not any(root == allowed or root.is_relative_to(allowed) for allowed in self._knowledge.roots):
            raise PermissionDeniedError(f"导入目录不在知识库白名单中：{directory}")

        report = ImportReport()
        documents = sorted(
            path for path in root.rglob("*") if path.is_file() and path.suffix.casefold() in {".txt", ".md", ".docx"}
        )
        for path in documents:
            report.scanned += 1
            try:
                changed = self._knowledge.ingest_document(path, force=force)
                if changed:
                    report.imported += 1
                    message = f"已导入 {path.name}"
                else:
                    report.skipped += 1
                    message = f"已跳过 {path.name}（索引未变化）"
            except Exception as exc:
                report.failures.append(ImportFailure(path.name, str(exc)))
                message = f"导入失败 {path.name}：{exc}"
            if progress:
                progress(message)
        return report


__all__ = ["ImportFailure", "ImportReport", "KnowledgeDocumentImporter"]
