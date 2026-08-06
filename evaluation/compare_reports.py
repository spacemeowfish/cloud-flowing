"""Validate two evaluation reports and generate a deterministic comparison."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ACCURACY_METRICS = (
    ("intent_accuracy", "意图准确率"),
    ("argument_accuracy", "参数提取准确率"),
    ("tool_accuracy", "工具选择准确率"),
    ("schema_compliance", "Schema 合规率"),
)
LATENCY_METRICS = (
    ("latency_p50_ms", "P50 延迟"),
    ("latency_p95_ms", "P95 延迟"),
    ("latency_p99_ms", "P99 延迟"),
)
DETAILED_ACCURACY_METRICS = (
    ("raw_intent_accuracy", "原始意图准确率"),
    ("raw_tool_accuracy", "原始工具准确率"),
    ("raw_contract_accuracy", "原始参数契约准确率"),
    ("raw_exact_argument_accuracy", "原始精确参数准确率"),
    ("normalized_contract_accuracy", "规范化后参数契约准确率"),
    ("semantic_match_rate", "语义匹配率"),
    ("end_to_end_accuracy", "端到端可执行准确率"),
)
INTENT_ORDER = (
    "file_open",
    "knowledge_query",
    "meeting_process",
    "reminder_create",
    "todo_manage",
    "schedule_manage",
    "text_polish",
)


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"报告必须是 JSON 对象：{path}")
    if not isinstance(payload.get("metrics"), dict) or not payload["metrics"]:
        raise ValueError(f"报告 metrics 为空：{path}")
    if not isinstance(payload.get("per_intent"), dict) or not payload["per_intent"]:
        raise ValueError(f"报告 per_intent 为空：{path}")
    if not isinstance(payload.get("failures", []), list):
        raise ValueError(f"报告 failures 不是数组：{path}")
    detailed = payload.get("detailed")
    if detailed is not None and (not isinstance(detailed, dict) or not isinstance(detailed.get("metrics"), dict)):
        raise ValueError(f"报告 detailed 格式无效：{path}")
    return payload


def _validate_same_structure(deepseek: dict[str, Any], qwen: dict[str, Any]) -> None:
    for section in ("metrics", "per_intent"):
        left = set(deepseek[section])
        right = set(qwen[section])
        if left != right:
            raise ValueError(f"两份报告的 {section} 字段不一致：{sorted(left ^ right)}")
    required_metrics = {name for name, _ in ACCURACY_METRICS + LATENCY_METRICS} | {"total"}
    missing = required_metrics - set(deepseek["metrics"])
    if missing:
        raise ValueError(f"报告缺少指标：{sorted(missing)}")
    missing_intents = set(INTENT_ORDER) - set(deepseek["per_intent"])
    if missing_intents:
        raise ValueError(f"报告缺少意图：{sorted(missing_intents)}")
    if deepseek["metrics"]["total"] != qwen["metrics"]["total"]:
        raise ValueError("两份报告的评测用例数量不一致")
    left_metadata = deepseek.get("run_metadata")
    right_metadata = qwen.get("run_metadata")
    if isinstance(left_metadata, dict) and isinstance(right_metadata, dict):
        left_digest = left_metadata.get("dataset_digest")
        right_digest = right_metadata.get("dataset_digest")
        if left_digest not in (None, "unknown") and right_digest not in (None, "unknown") and left_digest != right_digest:
            raise ValueError("两份报告的数据集摘要不一致，不能作为同集 A/B")
    deep_detailed = deepseek.get("detailed")
    qwen_detailed = qwen.get("detailed")
    if isinstance(deep_detailed, dict) and isinstance(qwen_detailed, dict):
        left = set(deep_detailed["metrics"])
        right = set(qwen_detailed["metrics"])
        if left != right:
            raise ValueError(f"两份报告的 detailed.metrics 字段不一致：{sorted(left ^ right)}")


def _load_cases(directory: Path) -> dict[str, dict[str, Any]]:
    cases: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError(f"用例文件必须是数组：{path}")
        for case in payload:
            case_id = str(case["id"])
            if case_id in cases:
                raise ValueError(f"重复用例 ID：{case_id}")
            cases[case_id] = case
    return cases


def _percent(value: float) -> str:
    return f"{value:.1%}"


def _pp(value: float) -> str:
    return f"{value * 100:+.1f} 个百分点"


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _failure_map(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item.get("id")): item for item in report.get("failures", [])}


def _actual(failure: dict[str, Any] | None) -> str:
    if failure is None:
        return "通过"
    actual = failure.get("actual_intent")
    dimensions = ", ".join(str(item) for item in failure.get("failed_dimensions", []))
    if actual:
        return f"{actual}（{dimensions}）" if dimensions else str(actual)
    return f"错误（{dimensions or '模型调用失败'}）"


def generate_comparison(
    deepseek_path: Path,
    qwen_path: Path,
    cases_directory: Path,
    output_path: Path,
    *,
    evaluated_at: datetime | None = None,
) -> str:
    deepseek = _load_json(deepseek_path)
    qwen = _load_json(qwen_path)
    _validate_same_structure(deepseek, qwen)
    cases = _load_cases(cases_directory)
    total = int(deepseek["metrics"]["total"])
    if len(cases) != total:
        raise ValueError(f"报告 total={total}，但固定用例集包含 {len(cases)} 条")

    deep_metrics = deepseek["metrics"]
    qwen_metrics = qwen["metrics"]
    deep_failures = _failure_map(deepseek)
    qwen_failures = _failure_map(qwen)
    timestamp = evaluated_at or datetime.now(ZoneInfo("Asia/Shanghai"))
    lines = [
        "# Agent Platform 模型对比评测报告",
        "",
        f"评测日期：{timestamp:%Y-%m-%d}",
        f"评测用例：{total} 条固定中文评测集",
        "差距列统一按“Qwen - DeepSeek”计算。准确率使用百分点，延迟使用毫秒。",
        "",
        "## 总览",
        "",
        "| 指标 | DeepSeek V4 Flash | Qwen2.5-3B 本地 | 差距 |",
        "|---|---:|---:|---:|",
    ]
    for key, label in ACCURACY_METRICS:
        lines.append(
            f"| {label} | {_percent(float(deep_metrics[key]))} | {_percent(float(qwen_metrics[key]))} | "
            f"{_pp(float(qwen_metrics[key]) - float(deep_metrics[key]))} |"
        )
    for key, label in LATENCY_METRICS:
        deep_value = float(deep_metrics[key])
        qwen_value = float(qwen_metrics[key])
        lines.append(f"| {label} | {deep_value:.1f} ms | {qwen_value:.1f} ms | {qwen_value - deep_value:+.1f} ms |")
    lines.append(f"| 失败用例数 | {len(deep_failures)} | {len(qwen_failures)} | {len(qwen_failures) - len(deep_failures):+d} |")

    deep_detailed = deepseek.get("detailed")
    qwen_detailed = qwen.get("detailed")
    if isinstance(deep_detailed, dict) and isinstance(qwen_detailed, dict):
        deep_detailed_metrics = deep_detailed["metrics"]
        qwen_detailed_metrics = qwen_detailed["metrics"]
        lines.extend(
            [
                "",
                "## 分层评测指标",
                "",
                "以下指标只在两份报告均启用 `--detailed` 时比较；旧版 `argument_accuracy` 始终保持原始精确参数口径。",
                "",
                "| 指标 | DeepSeek V4 Flash | Qwen2.5-3B 本地 | 差距 |",
                "|---|---:|---:|---:|",
            ]
        )
        for key, label in DETAILED_ACCURACY_METRICS:
            lines.append(
                f"| {label} | {_percent(float(deep_detailed_metrics[key]))} | "
                f"{_percent(float(qwen_detailed_metrics[key]))} | "
                f"{_pp(float(qwen_detailed_metrics[key]) - float(deep_detailed_metrics[key]))} |"
            )
        lines.append(
            f"| 语义覆盖率 | {_percent(float(deep_detailed_metrics['semantic_coverage']))} | "
            f"{_percent(float(qwen_detailed_metrics['semantic_coverage']))} | "
            f"{_pp(float(qwen_detailed_metrics['semantic_coverage']) - float(deep_detailed_metrics['semantic_coverage']))} |"
        )
        lines.append(
            f"| 待人工复核数 | {int(deep_detailed_metrics['needs_review_count'])} | "
            f"{int(qwen_detailed_metrics['needs_review_count'])} | "
            f"{int(qwen_detailed_metrics['needs_review_count']) - int(deep_detailed_metrics['needs_review_count']):+d} |"
        )
    elif isinstance(deep_detailed, dict) or isinstance(qwen_detailed, dict):
        lines.extend(
            [
                "",
                "## 分层评测指标",
                "",
                "- 只有一份报告启用了 `--detailed`，为避免混用评分口径，本次不计算分层指标差值。",
            ]
        )

    lines.extend(
        [
            "",
            "## 分意图准确率",
            "",
            "| 意图 | DeepSeek | Qwen | 差距 |",
            "|---|---:|---:|---:|",
        ]
    )
    for intent in INTENT_ORDER:
        deep_value = float(deepseek["per_intent"][intent])
        qwen_value = float(qwen["per_intent"][intent])
        lines.append(f"| {intent} | {_percent(deep_value)} | {_percent(qwen_value)} | {_pp(qwen_value - deep_value)} |")

    lines.extend(
        [
            "",
            "## 延迟与异常指标",
            "",
        ]
    )
    anomalies: list[str] = []
    for model_name, metrics in (("DeepSeek", deep_metrics), ("Qwen2.5-3B", qwen_metrics)):
        if float(metrics["latency_p95_ms"]) > 5000:
            anomalies.append(f"{model_name} P95 延迟超过 5 秒（{float(metrics['latency_p95_ms']):.1f} ms）")
        for key, label in ACCURACY_METRICS:
            if float(metrics[key]) < 0.8:
                anomalies.append(f"{model_name} {label}低于 80%（{_percent(float(metrics[key]))}）")
    if anomalies:
        lines.extend(f"- {item}" for item in anomalies)
    else:
        lines.append("- 未触发“P95 延迟 > 5 秒”或“准确率 < 80%”异常阈值。")

    lines.extend(
        [
            "",
            "## 失败用例分析",
            "",
            "| 用例 ID | 输入文本 | 期望意图 | DeepSeek 实际 | Qwen 实际 |",
            "|---|---|---|---|---|",
        ]
    )
    failed_ids = sorted(set(deep_failures) | set(qwen_failures))
    if failed_ids:
        for case_id in failed_ids:
            case = cases.get(case_id, {})
            lines.append(
                f"| {_cell(case_id)} | {_cell(case.get('input_text', '未知'))} | "
                f"{_cell(case.get('expected_intent', '未知'))} | {_cell(_actual(deep_failures.get(case_id)))} | "
                f"{_cell(_actual(qwen_failures.get(case_id)))} |"
            )
    else:
        lines.append("| - | 无失败用例 | - | 通过 | 通过 |")

    deep_intent = float(deep_metrics["intent_accuracy"])
    qwen_intent = float(qwen_metrics["intent_accuracy"])
    gap = qwen_intent - deep_intent
    recommendation = (
        "Qwen 可承担本地意图识别，但仍应保留云端回退与 Schema 校验。"
        if qwen_intent >= 0.8 and float(qwen_metrics["schema_compliance"]) >= 0.8
        else "Qwen 当前不宜独立承担本地编排，应优先修正提示词/量化配置并保留 DeepSeek 主路由。"
    )
    lines.extend(
        [
            "",
            "## 结论与建议",
            "",
            f"- 本地 Qwen 意图准确率 {_percent(qwen_intent)}，云端 DeepSeek {_percent(deep_intent)}，差距 {_pp(gap)}。",
            f"- DeepSeek P95 延迟 {float(deep_metrics['latency_p95_ms']):.1f} ms；Qwen P95 延迟 {float(qwen_metrics['latency_p95_ms']):.1f} ms。",
            f"- {recommendation}",
            "- 生产决策仍需在目标 RK3588 板卡上复测吞吐、内存、温升和并发；本报告仅代表当前 Windows/Ollama 环境。",
            "",
        ]
    )
    markdown = "\n".join(lines)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
    return markdown


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate DeepSeek/Qwen evaluation comparison")
    parser.add_argument("--deepseek", type=Path, required=True)
    parser.add_argument("--qwen", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    generate_comparison(args.deepseek, args.qwen, args.cases, args.output)
    print(args.output)


if __name__ == "__main__":
    main()
