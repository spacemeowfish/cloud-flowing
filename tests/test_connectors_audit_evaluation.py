import json
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from agent_platform.adapters.base_http_connector import ConnectorConfig, ConnectorRateLimitError, TokenBucket
from agent_platform.adapters.mock_adapter import MockModelAdapter
from agent_platform.adapters.weather_connector import MockWeatherConnector
from agent_platform.core.audit_service import AuditService
from agent_platform.core.data_classification import DataClassificationService
from agent_platform.core.evaluation_service import EvaluationService
from agent_platform.core.model_gateway import ModelGateway
from agent_platform.models import AuditEvent, AuditEventType


@pytest.mark.asyncio
async def test_token_bucket_limits_burst():
    bucket = TokenBucket(rate=0.01, capacity=3)
    for _ in range(3):
        await bucket.acquire()
    with pytest.raises(ConnectorRateLimitError):
        await bucket.acquire()


@pytest.mark.asyncio
async def test_weather_connector_degrades_after_retries():
    connector = MockWeatherConnector(
        ConnectorConfig(name="weather", rate_per_second=100, burst=10, retry_budget=2, degraded_seconds=30, fallback="cache")
    )
    connector.failures_remaining = 3
    result = await connector.execute({"city": "聊城"})
    assert result["status"] == "degraded"
    second = await connector.execute({"city": "聊城"})
    assert second["source"] == "mock-cache"
    await connector.close()


@pytest.mark.asyncio
async def test_audit_jsonl_chain_and_redaction(tmp_path):
    service = AuditService(tmp_path, DataClassificationService(), flush_size=3)
    task_id = uuid4()
    event_types = list(AuditEventType)[:7]
    for index, event_type in enumerate(event_types):
        await service.record(
            AuditEvent(
                task_id=task_id,
                event_type=event_type,
                input_summary="password=abc123" if index == 0 else "safe",
                output_summary="ok",
            )
        )
    await service.flush()
    events = await service.by_task(task_id)
    assert len(events) == 7
    raw = "".join(path.read_text(encoding="utf-8") for path in tmp_path.glob("*.jsonl"))
    assert "abc123" not in raw
    for line in raw.splitlines():
        json.loads(line)


@pytest.mark.asyncio
async def test_audit_retention(tmp_path):
    old = tmp_path / "audit-2020-01-01.jsonl"
    old.write_text("", encoding="utf-8")
    service = AuditService(tmp_path, DataClassificationService(), retention_days=30)
    removed = await service.purge_expired(now=datetime(2026, 7, 28))
    assert removed == 1


@pytest.mark.asyncio
async def test_sixty_case_evaluation_is_perfect_and_diff_works():
    gateway = ModelGateway(MockModelAdapter())
    service = EvaluationService(gateway)
    cases = service.load_cases(Path("evaluation/test_cases"))
    assert len(cases) == 60
    report = await service.run(cases)
    assert report.metrics.intent_accuracy == 1
    assert report.metrics.argument_accuracy == 1
    assert report.metrics.tool_accuracy == 1
    assert report.metrics.schema_compliance == 1
    compared = await service.run(cases, previous=report)
    assert all(value == 0 for value in compared.previous_diff.values())
