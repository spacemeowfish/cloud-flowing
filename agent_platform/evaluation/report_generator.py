"""Write JSON and concise Markdown evaluation reports."""

from pathlib import Path

from agent_platform.models import EvaluationReport


class ReportGenerator:
    @staticmethod
    def write(report: EvaluationReport, output: Path) -> tuple[Path, Path]:
        output.parent.mkdir(parents=True, exist_ok=True)
        json_path = output.with_suffix(".json")
        markdown_path = output.with_suffix(".md")
        json_path.write_text(report.model_dump_json(indent=2, exclude_none=True), encoding="utf-8")
        metrics = report.metrics
        lines = [
            "# Agent Evaluation Report",
            "",
            f"- Cases: {metrics.total}",
            f"- Intent accuracy: {metrics.intent_accuracy:.2%}",
            f"- Argument accuracy: {metrics.argument_accuracy:.2%}",
            f"- Tool accuracy: {metrics.tool_accuracy:.2%}",
            f"- Schema compliance: {metrics.schema_compliance:.2%}",
            f"- Latency P50/P95/P99: {metrics.latency_p50_ms:.2f}/{metrics.latency_p95_ms:.2f}/{metrics.latency_p99_ms:.2f} ms",
            "",
            "## Per Intent",
            *(f"- {name}: {value:.2%}" for name, value in sorted(report.per_intent.items())),
            "",
            "## Failures",
            *(f"- {item.get('id')}: {', '.join(item.get('failed_dimensions', []))}" for item in report.failures),
        ]
        if not report.failures:
            lines.append("- None")
        if report.detailed:
            detailed = report.detailed.metrics
            lines.extend(
                [
                    "",
                    "## Detailed Scoring",
                    "",
                    f"- Raw intent/tool/contract: {detailed.raw_intent_accuracy:.2%}/{detailed.raw_tool_accuracy:.2%}/{detailed.raw_contract_accuracy:.2%}",
                    f"- Raw exact arguments: {detailed.raw_exact_argument_accuracy:.2%}",
                    f"- Normalized contract: {detailed.normalized_contract_accuracy:.2%}",
                    f"- Semantic match/adjudicated/coverage: {detailed.semantic_match_rate:.2%}/{detailed.semantic_adjudicated_accuracy:.2%}/{detailed.semantic_coverage:.2%}",
                    f"- Needs review / model schema invalid: {detailed.needs_review_count}/{detailed.model_schema_invalid_count}",
                    f"- End-to-end accuracy: {detailed.end_to_end_accuracy:.2%}",
                ]
            )
        markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return json_path, markdown_path


__all__ = ["ReportGenerator"]
