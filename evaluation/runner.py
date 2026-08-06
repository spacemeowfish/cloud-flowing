"""Standalone evaluation entry point."""

import asyncio
from pathlib import Path

from agent_platform.api.container import ApplicationContainer
from agent_platform.config import get_settings
from agent_platform.core.evaluation_service import EvaluationService
from agent_platform.core.parameter_normalizer import normalize_arguments
from agent_platform.evaluation import ReportGenerator


async def run() -> None:
    container = ApplicationContainer.build(get_settings())
    await container.initialize()
    try:
        service = EvaluationService(container.gateway, registry=container.registry, normalizer=normalize_arguments)
        cases = service.load_cases(Path(__file__).parent / "test_cases")
        report = await service.run(cases)
        ReportGenerator.write(report, Path(__file__).parent / "reports" / "latest")
        print(report.model_dump_json(indent=2))
    finally:
        await container.close()


if __name__ == "__main__":
    asyncio.run(run())
