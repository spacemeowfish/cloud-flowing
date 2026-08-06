from pathlib import Path

import httpx
import pytest

from agent_platform.adapters.rkllm_adapter import RKLLMModelAdapter
from agent_platform.api.container import ApplicationContainer
from agent_platform.config import Settings
from agent_platform.core.evaluation_service import EvaluationService
from agent_platform.core.model_gateway import ModelGateway
from agent_platform.core.parameter_normalizer import normalize_arguments
from agent_platform.devtools.rkllm_mock_server import create_rkllm_mock_app


@pytest.mark.asyncio
async def test_rkllm_mock_server_models_and_busy_contract():
    transport = httpx.ASGITransport(app=create_rkllm_mock_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        models = await client.get("/v1/models")
        assert models.status_code == 200
        assert models.json()["data"][0]["owned_by"] == "rkllm"

        busy = await client.post(
            "/v1/chat/completions",
            headers={"x-rkllm-mock-mode": "busy"},
            json={
                "model": "rkllm",
                "messages": [{"role": "user", "content": "x"}],
                "stream": False,
                "enable_thinking": False,
            },
        )
        assert busy.status_code == 503
        assert busy.json()["error"]["type"] == "server_error"


@pytest.mark.asyncio
async def test_rkllm_protocol_simulator_passes_all_sixty_fixed_cases(tmp_path):
    settings = Settings(
        MODEL_PROVIDER="mock",
        AGENT_DATABASE_PATH=tmp_path / "agent.db",
        AGENT_AUDIT_DIR=tmp_path / "audit",
        AGENT_AUTHORIZED_FILE_ROOTS=[tmp_path / "files"],
        AGENT_KNOWLEDGE_ROOTS=[tmp_path / "knowledge"],
        AGENT_MEETING_OUTPUT_DIR=tmp_path / "meeting_notes",
    )
    container = ApplicationContainer.build(settings)
    await container.initialize()
    transport = httpx.ASGITransport(app=create_rkllm_mock_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        adapter = RKLLMModelAdapter(base_url="http://test/v1", client=client)
        gateway = ModelGateway(adapter)
        service = EvaluationService(gateway, registry=container.registry, normalizer=normalize_arguments)
        try:
            cases = service.load_cases(Path("evaluation/test_cases"))
            report = await service.run(cases)
            assert report.metrics.total == 60
            assert report.metrics.intent_accuracy == 1
            assert report.metrics.argument_accuracy == 1
            assert report.metrics.tool_accuracy == 1
            assert report.metrics.schema_compliance == 1
        finally:
            await service.close()
            await gateway.close()
            await container.close()
