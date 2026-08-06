"""REST and SSE routes for the Agent Core."""

import asyncio
import json
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from agent_platform.api.container import ApplicationContainer
from agent_platform.models import TERMINAL_STATES, AuditEvent, TaskCancel, TaskConfirmation, TaskCreate, TaskRecord


router = APIRouter()


TASK_LIFECYCLE = (
    "received",
    "understanding",
    "validating",
    "awaiting_confirmation",
    "executing",
    "delivering",
    "completed",
    "failed",
    "cancelled",
    "waiting_network",
)


def _container(request: Request) -> ApplicationContainer:
    return request.app.state.container


@router.post("/tasks", response_model=TaskRecord, status_code=201)
async def create_task(payload: TaskCreate, request: Request) -> TaskRecord:
    session_id = request.state.session_id if payload.session_id == "default" else payload.session_id
    normalized = payload.model_copy(update={"role": request.state.role, "session_id": session_id})
    container = _container(request)
    task = await container.agent.start(normalized)

    async def process_after_response() -> None:
        await asyncio.sleep(0.05)
        await container.agent.process(task.id, normalized)

    container.spawn(process_after_response())
    return task


@router.get("/tasks", response_model=list[TaskRecord])
async def list_tasks(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[TaskRecord]:
    """List newest tasks belonging to the authenticated browser session."""

    return await _container(request).tasks.list(request.state.session_id, limit)


@router.get("/tasks/{task_id}", response_model=TaskRecord)
async def get_task(task_id: UUID, request: Request) -> TaskRecord:
    task = await _container(request).tasks.get(task_id)
    if task.session_id != request.state.session_id:
        raise HTTPException(status_code=403, detail="Task belongs to another session")
    return task


@router.post("/tasks/{task_id}/confirm", response_model=TaskRecord)
async def confirm_task(task_id: UUID, payload: TaskConfirmation, request: Request) -> TaskRecord:
    task = await _container(request).tasks.get(task_id)
    if task.session_id != request.state.session_id:
        raise HTTPException(status_code=403, detail="Task belongs to another session")
    return await _container(request).agent.confirm(task_id, payload)


@router.post("/tasks/{task_id}/cancel", response_model=TaskRecord)
async def cancel_task(task_id: UUID, payload: TaskCancel, request: Request) -> TaskRecord:
    task = await _container(request).tasks.get(task_id)
    if task.session_id != request.state.session_id:
        raise HTTPException(status_code=403, detail="Task belongs to another session")
    return await _container(request).agent.cancel(task_id, payload.reason)


@router.get("/tasks/{task_id}/audit", response_model=list[AuditEvent])
async def task_audit(task_id: UUID, request: Request) -> list[AuditEvent]:
    task = await _container(request).tasks.get(task_id)
    if task.session_id != request.state.session_id:
        raise HTTPException(status_code=403, detail="Task belongs to another session")
    return await _container(request).audit.by_task(task_id)


@router.get("/tasks/{task_id}/events")
async def task_events(task_id: UUID, request: Request) -> StreamingResponse:
    container = _container(request)
    task = await container.tasks.get(task_id)
    if task.session_id != request.state.session_id:
        raise HTTPException(status_code=403, detail="Task belongs to another session")
    queue = await container.tasks.subscribe(task_id)

    async def stream():
        try:
            current = await container.tasks.get(task_id)
            yield f"event: task\ndata: {current.model_dump_json()}\n\n"
            while current.state not in TERMINAL_STATES and not await request.is_disconnected():
                try:
                    current = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"event: task\ndata: {current.model_dump_json()}\n\n"
                except TimeoutError:
                    yield "event: keepalive\ndata: {}\n\n"
        finally:
            container.tasks.unsubscribe(task_id, queue)

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.get("/health")
async def health(request: Request) -> dict[str, object]:
    return {
        "status": "ok",
        "model_provider": _container(request).settings.model_provider,
        "connectors": await _container(request).connections.health(),
    }


@router.get("/meta/capabilities")
async def capabilities(request: Request) -> dict[str, object]:
    """Expose non-secret runtime and tool contracts for operator UIs."""

    container = _container(request)
    settings = container.settings
    tools = [
        container.registry.get(name).metadata.model_dump(mode="json")
        for name in container.registry.names()
    ]
    return {
        "platform": {
            "name": "Agent Platform MVP",
            "version": "0.1.0",
            "model_provider": settings.model_provider,
            "model_name": settings.model_name,
            "resource_mode": settings.resource_mode,
            "timezone": settings.timezone,
            "network_available": settings.network_available,
            "file_open_enabled": settings.file_open_enabled,
            "retention_days": settings.retention_days,
        },
        "task_lifecycle": list(TASK_LIFECYCLE),
        "tools": tools,
        "authorized_roots": {
            "files": [str(path.resolve()) for path in settings.authorized_file_roots],
            "knowledge": [str(path.resolve()) for path in settings.knowledge_roots],
            "meeting_output": str(settings.meeting_output_dir.resolve()),
        },
        "safety": {
            "session_isolation": True,
            "audit_available": True,
            "confirmation_levels": ["R2", "R3"],
            "secret_values_exposed": False,
        },
    }


__all__ = ["router"]
