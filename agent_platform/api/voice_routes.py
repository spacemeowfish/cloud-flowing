"""Local push-to-talk endpoints."""

from uuid import UUID

from fastapi import APIRouter, Request

from agent_platform.models.voice import VoiceDevice, VoiceRecording, VoiceStatus


router = APIRouter(prefix="/voice", tags=["voice-input"])


@router.get("/status", response_model=VoiceStatus)
async def voice_status(request: Request) -> VoiceStatus:
    return request.app.state.container.voice.status()


@router.get("/devices", response_model=list[VoiceDevice])
async def voice_devices(request: Request) -> list[VoiceDevice]:
    return request.app.state.container.voice.devices()


@router.post("/recordings", response_model=VoiceRecording, status_code=201)
async def start_recording(request: Request) -> VoiceRecording:
    return request.app.state.container.voice.start(request.state.session_id)


@router.post("/recordings/{recording_id}/stop", response_model=VoiceRecording)
async def stop_recording(recording_id: UUID, request: Request) -> VoiceRecording:
    return await request.app.state.container.voice.stop(recording_id, request.state.session_id)


@router.post("/recordings/{recording_id}/cancel", response_model=VoiceRecording)
async def cancel_recording(recording_id: UUID, request: Request) -> VoiceRecording:
    return request.app.state.container.voice.cancel(recording_id, request.state.session_id)


__all__ = ["router"]
