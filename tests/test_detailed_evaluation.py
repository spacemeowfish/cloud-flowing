import json
from collections.abc import Sequence

import pytest

from agent_platform.core.evaluation_service import EvaluationService
from agent_platform.core.errors import ModelError
from agent_platform.core.model_gateway import ModelGateway
from agent_platform.core.tool_registry import ToolRegistry
from agent_platform.models import DataLevel, EvaluationCase, ModelMessage, RiskLevel, ToolMetadata
from agent_platform.models.evaluation import RawEvaluationSnapshot
from evaluation.dry_run_container import EvaluationDryRunContainer


class SequenceAdapter:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self._responses = list(responses)
        self.calls = 0

    async def generate(
        self,
        messages: Sequence[ModelMessage],
        response_schema: dict[str, object],
        max_tokens: int = 512,
    ) -> dict[str, object]:
        del messages, response_schema, max_tokens
        self.calls += 1
        return self._responses.pop(0)

    async def close(self) -> None:
        return None


class InvalidStructuredAdapter(SequenceAdapter):
    async def generate(
        self,
        messages: Sequence[ModelMessage],
        response_schema: dict[str, object],
        max_tokens: int = 512,
    ) -> dict[str, object]:
        del messages, response_schema, max_tokens
        self.calls += 1
        raise ModelError("Cloud model returned invalid structured JSON")


class MetadataOnlyTool:
    def __init__(self, name: str, schema: dict[str, object]) -> None:
        self._metadata = ToolMetadata(
            name=name,
            description=f"test {name}",
            parameters_schema=schema,
            risk_level=RiskLevel.R0,
            data_level=DataLevel.D0,
        )

    @property
    def metadata(self) -> ToolMetadata:
        return self._metadata


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    schemas = {
        "file_open": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"], "additionalProperties": False},
        "general_chat": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"], "additionalProperties": False},
        "knowledge_query": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"], "additionalProperties": False},
        "meeting_process": {"type": "object", "properties": {"source_path": {"type": "string"}}, "required": ["source_path"], "additionalProperties": False},
        "reminder_create": {"type": "object", "properties": {"action": {"type": "string"}}, "required": ["action"], "additionalProperties": False},
        "todo_manage": {"type": "object", "properties": {"action": {"type": "string"}}, "required": ["action"], "additionalProperties": False},
        "schedule_manage": {"type": "object", "properties": {"action": {"type": "string"}}, "required": ["action"], "additionalProperties": False},
        "text_polish": {"type": "object", "properties": {"operation": {"type": "string"}, "text": {"type": "string"}}, "required": ["operation", "text"], "additionalProperties": False},
    }
    for name, schema in schemas.items():
        registry.register(MetadataOnlyTool(name, schema))
    registry.freeze()
    return registry


@pytest.mark.asyncio
async def test_detailed_evaluation_records_invalid_model_case_and_continues(tmp_path):
    adapter = SequenceAdapter(
        [
            {"intent": "knowledge_query", "confidence": 0.9},
            {"arguments": {}},
            {"arguments": {}},
            {"intent": "knowledge_query", "confidence": 0.9},
            {"arguments": {"query": "valid case"}, "missing_fields": []},
        ]
    )
    service = EvaluationService(ModelGateway(adapter), registry=_registry())
    cases = [
        # These neutral inputs deliberately bypass deterministic pre-routing so
        # this test continues to exercise model-schema repair and recovery.
        EvaluationCase(id="invalid", input_text="invalid case", expected_intent="knowledge_query", expected_tool="knowledge_query", expected_arguments={"query": "invalid case"}),
        EvaluationCase(
            id="valid",
            input_text="valid case",
            expected_intent="knowledge_query",
            expected_tool="knowledge_query",
            expected_arguments={"query": "valid case"},
            expected_pipeline_outcome="executed",
        ),
    ]
    snapshot_path = tmp_path / "raw.jsonl"
    try:
        report = await service.run(cases, detailed=True, capture_raw=snapshot_path)
    finally:
        await service.close()

    assert adapter.calls == 5
    assert report.metrics.total == 2
    assert report.metrics.schema_compliance == 0.5
    assert len(report.failures) == 1
    assert report.detailed is not None
    assert report.detailed.metrics.model_schema_invalid_count == 1
    assert report.detailed.metrics.raw_intent_accuracy == 0.5
    assert report.detailed.metrics.end_to_end_accuracy == 0.5
    snapshots = EvaluationService.load_raw_snapshots(snapshot_path)
    assert snapshots["invalid"].raw_result == {"arguments": {}}
    assert len(snapshot_path.read_text(encoding="utf-8").splitlines()) == 2


@pytest.mark.asyncio
async def test_snapshot_replay_uses_pre_registered_alias_without_model_call(tmp_path):
    adapter = SequenceAdapter([])
    case = EvaluationCase(
        id="knowledge-alias",
        input_text="公司报销标准是什么",
        expected_intent="knowledge_query",
        expected_tool="knowledge_query",
        expected_arguments={"query": "公司报销标准是什么"},
        aliases={"query": ["公司报销标准"]},
    )
    raw_path = tmp_path / "raw.jsonl"
    raw_path.write_text(
        json.dumps(
            {
                "case_id": case.id,
                "input_hash": __import__("hashlib").sha256(case.input_text.encode("utf-8")).hexdigest(),
                "provider": "test",
                "model": "test",
                "prompt_version": "v1",
                "raw_result": {"intent": "knowledge_query", "arguments": {"query": "公司报销标准"}, "missing_fields": [], "confidence": 0.9},
                "model_error": None,
                "latency_ms": 1,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    service = EvaluationService(ModelGateway(adapter), registry=_registry())
    try:
        report = await service.run(
            [case],
            detailed=True,
            raw_snapshots=EvaluationService.load_raw_snapshots(raw_path),
        )
    finally:
        await service.close()

    assert adapter.calls == 0
    assert report.metrics.argument_accuracy == 0
    assert report.detailed is not None
    assert report.detailed.cases[0].semantic_status == "match"
    assert report.detailed.metrics.semantic_coverage == 1


@pytest.mark.asyncio
async def test_detailed_evaluation_marks_cloud_invalid_json_as_model_schema_invalid():
    service = EvaluationService(ModelGateway(InvalidStructuredAdapter([])), registry=_registry())
    case = EvaluationCase(
        id="malformed-json",
        input_text="malformed case",
        expected_intent="knowledge_query",
        expected_tool="knowledge_query",
        expected_arguments={"query": "malformed case"},
    )
    try:
        report = await service.run([case], detailed=True)
    finally:
        await service.close()

    assert report.detailed is not None
    assert report.detailed.metrics.model_schema_invalid_count == 1
    assert report.detailed.cases[0].model_schema_invalid is True


@pytest.mark.asyncio
async def test_snapshot_replay_preserves_cloud_invalid_json_schema_classification():
    service = EvaluationService(ModelGateway(SequenceAdapter([])), registry=_registry())
    case = EvaluationCase(
        id="historical-malformed-json",
        input_text="\u67e5\u8be2\u4fdd\u4fee\u671f",
        expected_intent="knowledge_query",
        expected_tool="knowledge_query",
        expected_arguments={"query": "\u4fdd\u4fee\u671f"},
    )
    snapshot = RawEvaluationSnapshot(
        case_id=case.id,
        input_hash=__import__("hashlib").sha256(case.input_text.encode("utf-8")).hexdigest(),
        model_error="ModelError: Cloud model returned invalid structured JSON",
    )
    try:
        report = await service.run([case], detailed=True, raw_snapshots={case.id: snapshot})
    finally:
        await service.close()

    assert report.detailed is not None
    assert report.detailed.metrics.model_schema_invalid_count == 1


@pytest.mark.asyncio
async def test_delete_all_dry_run_stops_at_r3_confirmation_before_tool_execution():
    dry_run = EvaluationDryRunContainer(_registry())
    service = EvaluationService(ModelGateway(SequenceAdapter([])), registry=_registry(), dry_run_container=dry_run)
    case = EvaluationCase(
        id="delete-all",
        input_text="删除所有提醒",
        expected_intent="reminder_create",
        expected_tool="reminder_create",
        expected_arguments={"action": "delete_all"},
        expected_pipeline_outcome="awaiting_confirmation",
    )
    raw = {
        "case_id": case.id,
        "input_hash": __import__("hashlib").sha256(case.input_text.encode("utf-8")).hexdigest(),
        "provider": "test",
        "model": "test",
        "prompt_version": "v1",
        "raw_result": {"intent": "reminder_create", "arguments": {"action": "delete_all"}, "missing_fields": [], "confidence": 0.9},
        "latency_ms": 1,
    }
    try:
        report = await service.run([case], detailed=True, raw_snapshots={case.id: RawEvaluationSnapshot.model_validate(raw)})
    finally:
        await service.close()

    assert report.detailed is not None
    assert report.detailed.cases[0].pipeline_outcome == "awaiting_confirmation"
    assert report.detailed.cases[0].end_to_end_ok is True
    assert dry_run.executed_tools == []
