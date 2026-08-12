"""Push-to-talk API models."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class VoiceDevice(BaseModel):
    id: str
    name: str
    channels: int = Field(..., ge=1)
    default: bool = False


class VoiceRecording(BaseModel):
    id: UUID
    state: str
    started_at: datetime
    duration_seconds: float = 0.0
    level_dbfs: float = -90.0
    transcript: str | None = None
    limit_reached: bool = False


class VoiceStatus(BaseModel):
    enabled: bool
    available: bool
    state: str
    model_path: str
    model_exists: bool
    selected_device: str
    max_recording_seconds: float = 30.0
    active_recording_id: UUID | None = None
    level_dbfs: float = -90.0
    message: str = ""


__all__ = ["VoiceDevice", "VoiceRecording", "VoiceStatus"]
