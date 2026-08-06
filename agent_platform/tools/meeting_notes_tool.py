"""Authorized local transcript-to-minutes tool."""

import hashlib
import json
from pathlib import Path

from pydantic import JsonValue

from agent_platform.core.data_classification import DataClassificationService
from agent_platform.core.errors import PermissionDeniedError
from agent_platform.core.interfaces import Tool
from agent_platform.models import DataLevel, RiskLevel, ToolMetadata, ToolReceipt
from agent_platform.tools.meeting_processor import MeetingProcessor


class MeetingNotesTool(Tool):
    def __init__(self, roots: list[Path], output_dir: Path, classifier: DataClassificationService) -> None:
        self._roots = tuple(root.resolve() for root in roots)
        self._output_dir = output_dir.resolve()
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._classifier = classifier
        self._processor = MeetingProcessor()

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="meeting_process",
            description="Create traceable Markdown minutes from an authorized TXT or MD transcript",
            parameters_schema={
                "type": "object",
                "properties": {"source_path": {"type": "string", "minLength": 1}},
                "required": ["source_path"],
                "additionalProperties": False,
            },
            risk_level=RiskLevel.R2,
            data_level=DataLevel.D2,
            timeout_seconds=30,
        )

    def idempotency_key(self, arguments: dict[str, JsonValue]) -> str:
        value = json.dumps(arguments, ensure_ascii=False, sort_keys=True)
        return f"meeting:{hashlib.sha256(value.encode()).hexdigest()}"

    async def execute(self, arguments: dict[str, JsonValue]) -> ToolReceipt:
        source = Path(str(arguments["source_path"])).resolve()
        if source.suffix.casefold() not in {".txt", ".md"} or not source.is_file():
            raise PermissionDeniedError("Meeting source must be an existing TXT or MD file")
        if not any(source.is_relative_to(root) for root in self._roots):
            raise PermissionDeniedError("Meeting source is outside authorized roots")
        text = source.read_text(encoding="utf-8")
        classified = self._classifier.classify(text)
        markdown, metadata = self._processor.process(classified.redacted_text, source)
        output_path = self._output_dir / f"{source.stem}-会议纪要.md"
        output_path.write_text(markdown, encoding="utf-8")
        return ToolReceipt(
            tool_name=self.metadata.name,
            actual_arguments=arguments,
            success=True,
            output_summary=f"会议纪要已生成：{output_path.name}",
            output={"output_path": str(output_path), **metadata},
        )


__all__ = ["MeetingNotesTool"]

