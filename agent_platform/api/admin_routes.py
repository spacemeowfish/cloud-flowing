"""Local-only desktop administration endpoints."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, Request

from agent_platform.adapters.notifications import windows_toast
from agent_platform.api.container import ApplicationContainer
from agent_platform.api.auth import require_developer
from agent_platform.core.desktop_settings import DesktopSettingsService, PassiveRestartController
from agent_platform.models.admin import DesktopSettingsUpdate, DesktopSettingsView, RestartStatus
from agent_platform.tools import KnowledgeBaseTool, KnowledgeDocumentImporter


router = APIRouter(prefix="/admin", tags=["desktop-admin"], dependencies=[Depends(require_developer)])


def _container(request: Request) -> ApplicationContainer:
    return request.app.state.container


def _settings_service(request: Request) -> DesktopSettingsService:
    controller = getattr(request.app.state, "restart_controller", None) or PassiveRestartController()
    return DesktopSettingsService(_container(request).settings, controller)


@router.get("/settings", response_model=DesktopSettingsView)
async def get_settings(request: Request) -> DesktopSettingsView:
    return await _settings_service(request).view()


@router.put("/settings", response_model=DesktopSettingsView)
async def update_settings(payload: DesktopSettingsUpdate, request: Request) -> DesktopSettingsView:
    return await _settings_service(request).update(payload)


@router.get("/restart-status", response_model=RestartStatus)
async def restart_status(request: Request) -> RestartStatus:
    controller = getattr(request.app.state, "restart_controller", None) or PassiveRestartController()
    return controller.status()


def _reindex(knowledge: KnowledgeBaseTool) -> dict[str, object]:
    # Reuse the container's live instance: it is built from
    # settings.document_roots, so the rebuilt index can never diverge from
    # what queries actually read (knowledge_roots may differ when
    # AGENT_DOCUMENT_ROOTS is explicitly configured).
    aggregate = {"scanned": 0, "imported": 0, "skipped": 0, "failures": []}
    importer = KnowledgeDocumentImporter(knowledge)
    for root in knowledge.roots:
        report = importer.import_directory(Path(root), force=True)
        aggregate["scanned"] += report.scanned
        aggregate["imported"] += report.imported
        aggregate["skipped"] += report.skipped
        aggregate["failures"].extend(
            {"file": failure.file, "error": failure.error} for failure in report.failures
        )
    return aggregate


@router.post("/knowledge/reindex")
async def reindex_knowledge(request: Request) -> dict[str, object]:
    return await asyncio.to_thread(_reindex, _container(request).knowledge)


@router.post("/notifications/test")
async def test_notification(request: Request) -> dict[str, object]:
    await windows_toast({"text": "云湃 Agent 桌面通知测试"})
    return {"sent": True, "message": "云湃 Agent 桌面通知测试"}


__all__ = ["router"]
