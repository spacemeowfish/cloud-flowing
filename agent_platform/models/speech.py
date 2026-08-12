"""Text-to-speech API contracts."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from agent_platform.models.common import StrictModel


class SpeechCreate(StrictModel):
    """Request a fresh speech version for a completed task."""

    voice_id: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")


class SpeechArtifact(StrictModel):
    task_id: UUID
    version_id: UUID
    voice_id: str = Field(..., min_length=1)
    voice_label: str = Field(..., min_length=1)
    audio_url: str = Field(..., min_length=1)
    content_type: str = "audio/wav"
    sample_rate: int = Field(..., ge=8000, le=192000)
    duration_seconds: float = Field(..., gt=0)
    created_at: datetime


__all__ = ["SpeechArtifact", "SpeechCreate"]
