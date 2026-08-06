import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from evaluation.compare_reports import generate_comparison


def _write_report(path: Path, *, intent: float, p95: float, failure: bool) -> None:
    failures = []
    if failure:
        failures.append(
            {
                "id": "file-01",
                "expected_intent": "file_open",
                "actual_intent": "knowledge_query",
                "failed_dimensions": ["intent", "tool"],
            }
        )
    payload = {
        "metrics": {
            "total": 7,
            "intent_accuracy": intent,
            "argument_accuracy": 0.8,
            "tool_accuracy": intent,
            "schema_compliance": 1.0,
            "latency_p50_ms": 100.0,
            "latency_p95_ms": p95,
            "latency_p99_ms": p95 + 20,
        },
        "per_intent": {
            "file_open": intent,
            "knowledge_query": 1.0,
            "meeting_process": 1.0,
            "reminder_create": 1.0,
            "todo_manage": 1.0,
            "schedule_manage": 1.0,
            "text_polish": 1.0,
        },
        "failures": failures,
        "previous_diff": {},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_cases(directory: Path) -> None:
    directory.mkdir()
    intents = ["file_open", "knowledge_query", "meeting_process", "reminder_create", "todo_manage", "schedule_manage", "text_polish"]
    for index, intent in enumerate(intents):
        case_id = "file-01" if index == 0 else f"case-{index}"
        payload = [{"id": case_id, "input_text": f"输入 {index}", "expected_intent": intent}]
        (directory / f"{intent}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_generate_comparison_has_exact_metrics_failures_and_conclusion(tmp_path):
    deepseek = tmp_path / "deepseek.json"
    qwen = tmp_path / "qwen.json"
    cases = tmp_path / "cases"
    output = tmp_path / "comparison.md"
    _write_report(deepseek, intent=1.0, p95=500.0, failure=False)
    _write_report(qwen, intent=0.8, p95=6000.0, failure=True)
    _write_cases(cases)

    markdown = generate_comparison(
        deepseek,
        qwen,
        cases,
        output,
        evaluated_at=datetime(2026, 7, 28, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert output.read_text(encoding="utf-8") == markdown
    assert "| 意图准确率 | 100.0% | 80.0% | -20.0 个百分点 |" in markdown
    assert "| P95 延迟 | 500.0 ms | 6000.0 ms | +5500.0 ms |" in markdown
    assert "| file-01 | 输入 0 | file_open | 通过 | knowledge_query（intent, tool） |" in markdown
    assert "本地 Qwen 意图准确率 80.0%，云端 DeepSeek 100.0%，差距 -20.0 个百分点" in markdown
    assert "Qwen2.5-3B P95 延迟超过 5 秒" in markdown


def test_generate_comparison_rejects_different_structures(tmp_path):
    deepseek = tmp_path / "deepseek.json"
    qwen = tmp_path / "qwen.json"
    cases = tmp_path / "cases"
    _write_report(deepseek, intent=1.0, p95=500.0, failure=False)
    _write_report(qwen, intent=0.8, p95=600.0, failure=False)
    payload = json.loads(qwen.read_text(encoding="utf-8"))
    del payload["metrics"]["latency_p99_ms"]
    qwen.write_text(json.dumps(payload), encoding="utf-8")
    _write_cases(cases)

    with pytest.raises(ValueError, match="metrics 字段不一致"):
        generate_comparison(deepseek, qwen, cases, tmp_path / "comparison.md")
