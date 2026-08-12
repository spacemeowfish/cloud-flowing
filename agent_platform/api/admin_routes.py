"""Local-only desktop administration endpoints."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from agent_platform.adapters.notifications import windows_toast
from agent_platform.api.container import ApplicationContainer
from agent_platform.core.data_classification import DataClassificationService
from agent_platform.core.desktop_settings import DesktopSettingsService, PassiveRestartController
from agent_platform.models.admin import DesktopSettingsUpdate, DesktopSettingsView, RestartStatus
from agent_platform.tools import KnowledgeBaseTool, KnowledgeDocumentImporter


router = APIRouter(prefix="/admin", tags=["desktop-admin"])


def _local_only(request: Request) -> None:
    if request.client is not None and request.client.host not in {"127.0.0.1", "::1", "testclient", "test"}:
        raise HTTPException(status_code=403, detail="Desktop administration is localhost only")


def _container(request: Request) -> ApplicationContainer:
    return request.app.state.container


def _settings_service(request: Request) -> DesktopSettingsService:
    controller = getattr(request.app.state, "restart_controller", None) or PassiveRestartController()
    return DesktopSettingsService(_container(request).settings, controller)


@router.get("/settings", response_model=DesktopSettingsView)
async def get_settings(request: Request) -> DesktopSettingsView:
    _local_only(request)
    return await _settings_service(request).view()


@router.put("/settings", response_model=DesktopSettingsView)
async def update_settings(payload: DesktopSettingsUpdate, request: Request) -> DesktopSettingsView:
    _local_only(request)
    return await _settings_service(request).update(payload)


@router.get("/restart-status", response_model=RestartStatus)
async def restart_status(request: Request) -> RestartStatus:
    _local_only(request)
    controller = getattr(request.app.state, "restart_controller", None) or PassiveRestartController()
    return controller.status()


def _reindex(settings) -> dict[str, object]:
    knowledge = KnowledgeBaseTool(
        list(settings.knowledge_roots),
        settings.database_path.with_name("knowledge.db"),
        DataClassificationService(),
    )
    aggregate = {"scanned": 0, "imported": 0, "skipped": 0, "failures": []}
    try:
        importer = KnowledgeDocumentImporter(knowledge)
        for root in settings.knowledge_roots:
            report = importer.import_directory(Path(root), force=True)
            aggregate["scanned"] += report.scanned
            aggregate["imported"] += report.imported
            aggregate["skipped"] += report.skipped
            aggregate["failures"].extend(
                {"file": failure.file, "error": failure.error} for failure in report.failures
            )
        return aggregate
    finally:
        knowledge.close()


@router.post("/knowledge/reindex")
async def reindex_knowledge(request: Request) -> dict[str, object]:
    _local_only(request)
    return await asyncio.to_thread(_reindex, _container(request).settings)


@router.post("/notifications/test")
async def test_notification(request: Request) -> dict[str, object]:
    _local_only(request)
    await windows_toast({"text": "云湃 Agent 桌面通知测试"})
    return {"sent": True, "message": "云湃 Agent 桌面通知测试"}


__all__ = ["router"]
