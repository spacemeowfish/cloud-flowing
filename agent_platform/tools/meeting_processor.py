"""Deterministic transcript segmentation and traceable Markdown minutes."""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


_SPEAKER = re.compile(r"^(?:#{1,3}\s*)?([\w\u4e00-\u9fff]{1,20})(?:说)?[：:]\s*(.+)$")


@dataclass(frozen=True)
class Segment:
    index: int
    speaker: str
    text: str


class MeetingProcessor:
    def segment(self, transcript: str) -> list[Segment]:
        segments: list[Segment] = []
        for line_number, line in enumerate(transcript.splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            match = _SPEAKER.match(line)
            if match:
                speaker, text = match.groups()
            else:
                speaker, text = "未标注", line
            segments.append(Segment(line_number, speaker, text))
        return segments

    def process(self, transcript: str, source: Path) -> tuple[str, dict[str, object]]:
        segments = self.segment(transcript)
        if not segments:
            raise ValueError("会议文字稿为空")
        conclusions = [item for item in segments if any(key in item.text for key in ("决定", "结论", "确认", "通过"))]
        disagreements = [item for item in segments if any(key in item.text for key in ("不同意", "分歧", "反对", "待定"))]
        actions = [item for item in segments if any(key in item.text for key in ("负责", "请", "行动项", "截止", "完成"))]
        discussion = segments[: min(8, len(segments))]
        topic = source.stem

        def bullet(item: Segment) -> str:
            return f"- {item.speaker}：{item.text} [来源：L{item.index}]"

        conclusion_lines = [bullet(item) for item in conclusions] or ["- 未形成明确结论"]
        disagreement_lines = [bullet(item) for item in disagreements] or ["- 未识别到明确分歧"]
        action_lines = [bullet(item) for item in actions] or ["- 未识别到明确行动项"]
        lines = [
            f"# {topic}会议纪要",
            "",
            "## 元数据",
            f"- 处理时间：{datetime.now(UTC).isoformat()}",
            f"- 原始文件：{source.name}",
            f"- 字数统计：{len(transcript)}",
            "",
            "## 主要讨论点",
            *(bullet(item) for item in discussion),
            "",
            "## 结论",
            *conclusion_lines,
            "",
            "## 分歧点",
            *disagreement_lines,
            "",
            "## 行动项",
            *action_lines,
        ]
        markdown = "\n".join(lines) + "\n"
        metadata = {
            "topic": topic,
            "segments": len(segments),
            "conclusions": len(conclusions),
            "disagreements": len(disagreements),
            "actions": len(actions),
            "traceable": True,
        }
        return markdown, metadata


__all__ = ["MeetingProcessor", "Segment"]
