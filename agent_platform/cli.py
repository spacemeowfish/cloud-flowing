"""Command-line entry point for serving, demoing, and evaluating the MVP."""

import argparse
import asyncio
import hashlib
import json
import tempfile
from pathlib import Path

import uvicorn

from agent_platform.api.container import ApplicationContainer
from agent_platform.adapters.structured_response import INTENT_PROMPT_VERSION
from agent_platform.config import get_settings
from agent_platform.core.evaluation_service import EvaluationService
from agent_platform.core.parameter_normalizer import normalize_arguments
from agent_platform.core.data_classification import DataClassificationService
from agent_platform.models import EvaluationReport, TaskCreate
from agent_platform.tools import KnowledgeBaseTool, KnowledgeDocumentImporter


async def _demo() -> None:
    settings = get_settings()
    container = ApplicationContainer.build(settings)
    await container.initialize()
    try:
        task = await container.agent.submit(TaskCreate(text="查询本地知识库中的产品保修期"))
        print(task.model_dump_json(indent=2))
    finally:
        await container.close()


async def _evaluate(
    directory: Path,
    output: Path,
    *,
    detailed: bool = False,
    raw_snapshot: Path | None = None,
    capture_raw: Path | None = None,
    prompt_version: str = INTENT_PROMPT_VERSION,
    model_digest: str | None = None,
    previous_report: Path | None = None,
    previous_raw_snapshot: Path | None = None,
    expected_total: int | None = None,
) -> None:
    settings = get_settings()
    with tempfile.TemporaryDirectory(prefix="agent-platform-cli-evaluation-") as temporary_directory:
        root = Path(temporary_directory)
        evaluation_settings = settings.model_copy(
            update={
                "database_path": root / "agent_platform.db",
                "audit_dir": root / "audit",
                "authorized_file_roots": [root / "authorized_files"],
                "knowledge_roots": [root / "knowledge"],
                "meeting_output_dir": root / "meeting_notes",
                "file_open_enabled": False,
            }
        )
        container = ApplicationContainer.build(evaluation_settings)
        try:
            service = EvaluationService(
                container.gateway,
                registry=container.registry if detailed else None,
                normalizer=normalize_arguments if detailed else None,
            )
            cases = service.load_cases(directory)
            if expected_total is not None and len(cases) != expected_total:
                raise ValueError(f"Expected {expected_total} fixed cases, found {len(cases)}")
            rate_limit = 1.0 if settings.model_provider == "cloud" else None
            snapshots = EvaluationService.load_raw_snapshots(raw_snapshot) if raw_snapshot else None
            baseline_snapshots = (
                EvaluationService.load_raw_snapshots(previous_raw_snapshot) if previous_raw_snapshot else None
            )
            if baseline_snapshots is not None:
                EvaluationService.validate_snapshot_inputs(cases, baseline_snapshots)
            previous = (
                EvaluationReport.model_validate_json(previous_report.read_text(encoding="utf-8"))
                if previous_report
                else None
            )
            active_model = (
                settings.rkllm_model_name
                if settings.model_provider == "rkllm"
                else ("mock-deterministic" if settings.model_provider == "mock" else settings.model_name)
            )
            configured_digest = (
                settings.rkllm_model_digest if settings.model_provider == "rkllm" else settings.model_digest
            )
            report = await service.run(
                cases,
                previous=previous,
                rate_limit_per_second=rate_limit if snapshots is None else None,
                detailed=detailed,
                raw_snapshots=snapshots,
                capture_raw=capture_raw,
                snapshot_metadata={
                    "provider": settings.model_provider,
                    "model": active_model,
                    "model_digest": model_digest or configured_digest,
                    "prompt_version": prompt_version,
                    "baseline_report_digest": (
                        hashlib.sha256(previous_report.read_bytes()).hexdigest() if previous_report else "unknown"
                    ),
                    "baseline_snapshot_digest": (
                        hashlib.sha256(previous_raw_snapshot.read_bytes()).hexdigest()
                        if previous_raw_snapshot
                        else "unknown"
                    ),
                },
            )
            output.parent.mkdir(parents=True, exist_ok=True)
            serialized = report.model_dump_json(indent=2, exclude_none=True)
            output.write_text(serialized, encoding="utf-8")
            print(serialized)
        finally:
            if "service" in locals():
                await service.close()
            await container.close()


def _import_docs(directory: Path, *, force: bool = False) -> None:
    settings = get_settings()
    knowledge = KnowledgeBaseTool(
        settings.knowledge_roots,
        settings.database_path.with_name("knowledge.db"),
        DataClassificationService(),
    )
    try:
        report = KnowledgeDocumentImporter(knowledge).import_directory(
            directory,
            force=force,
            progress=print,
        )
        print(
            json.dumps(
                {
                    "scanned": report.scanned,
                    "imported": report.imported,
                    "skipped": report.skipped,
                    "failures": [failure.__dict__ for failure in report.failures],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        if report.failures:
            raise SystemExit(1)
    finally:
        knowledge.close()


def main() -> None:
    parser = argparse.ArgumentParser(prog="agent-platform")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("serve", help="Start the localhost FastAPI service")
    subparsers.add_parser("demo", help="Run one offline task")
    evaluate = subparsers.add_parser("evaluate", help="Run the fixed evaluation dataset")
    evaluate.add_argument("--mode", choices=["mock", "cloud", "rkllm"], default="mock")
    evaluate.add_argument("--cases", type=Path, default=Path("evaluation/test_cases"))
    evaluate.add_argument("--output", type=Path, default=Path("evaluation/reports/latest.json"))
    evaluate.add_argument("--detailed", action="store_true", help="Enable raw, normalized, and isolated dry-run scoring")
    evaluate.add_argument("--capture-raw", type=Path, help="Write replayable raw model output as JSONL")
    evaluate.add_argument("--raw-snapshot", type=Path, help="Replay a captured JSONL raw-output snapshot")
    evaluate.add_argument("--prompt-version", default=INTENT_PROMPT_VERSION, help="Prompt version stored in reports and raw snapshots")
    evaluate.add_argument("--model-digest", help="Exact model artifact digest stored in reports and raw snapshots")
    evaluate.add_argument("--previous-report", type=Path, help="Same-dataset baseline report used for metric diffs")
    evaluate.add_argument("--previous-raw-snapshot", type=Path, help="Baseline raw JSONL whose case IDs and input hashes must match")
    evaluate.add_argument("--expected-total", type=int, help="Fail before model calls unless the fixed dataset has this size")
    import_docs = subparsers.add_parser("import-docs", help="Import authorized documents into the local knowledge index")
    import_docs.add_argument("directory", type=Path)
    import_docs.add_argument("--force", action="store_true", help="Rebuild indexes even when files are unchanged")
    args = parser.parse_args()
    settings = get_settings()
    if args.command == "serve":
        uvicorn.run("agent_platform.api:app", host=settings.host, port=settings.port, reload=False)
    elif args.command == "demo":
        asyncio.run(_demo())
    elif args.command == "import-docs":
        _import_docs(args.directory, force=args.force)
    else:
        if args.mode != settings.model_provider:
            print(f"Warning: --mode={args.mode} but MODEL_PROVIDER={settings.model_provider}")
        asyncio.run(
            _evaluate(
                args.cases,
                args.output,
                detailed=args.detailed,
                raw_snapshot=args.raw_snapshot,
                capture_raw=args.capture_raw,
                prompt_version=args.prompt_version,
                model_digest=args.model_digest,
                previous_report=args.previous_report,
                previous_raw_snapshot=args.previous_raw_snapshot,
                expected_total=args.expected_total,
            )
        )


if __name__ == "__main__":
    main()


__all__ = ["main"]
