"""Safe desktop administration request and response models."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DesktopVoicePreset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    name: str = Field(..., min_length=1, max_length=40)
    reference_wav: Path
    reference_text: str = Field(..., min_length=1, max_length=1000)


class DesktopSettingsUpdate(BaseModel):
    """Editable non-secret settings accepted from the local workbench."""

    model_config = ConfigDict(extra="forbid")

    model_provider: str = Field(..., pattern=r"^(mock|ollama)$")
    model_name: str = Field(..., min_length=1, max_length=200)
    ollama_base_url: str = Field(..., min_length=1, max_length=500)
    file_open_enabled: bool
    authorized_file_roots: list[Path] = Field(..., min_length=1, max_length=20)
    knowledge_roots: list[Path] = Field(..., min_length=1, max_length=20)
    tts_provider: str = Field(..., pattern=r"^(disabled|zipvoice)$")
    zipvoice_model_dir: Path
    zipvoice_vocoder_path: Path
    zipvoice_num_threads: int = Field(..., ge=1, le=32)
    zipvoice_speed: float = Field(..., ge=0.5, le=2.0)
    zipvoice_default_voice_id: str = Field(..., min_length=1, max_length=64)
    zipvoice_voices: list[DesktopVoicePreset] = Field(default_factory=list, max_length=20)
    voice_enabled: bool
    voice_input_device: str = Field(default="", max_length=200)
    voice_model_dir: Path
    voice_cpu_threads: int = Field(..., ge=1, le=32)
    voice_num_workers: int = Field(..., ge=1, le=4)
    voice_beam_size: int = Field(..., ge=1, le=10)
    voice_vad_enabled: bool
    voice_max_recording_seconds: float = Field(..., ge=1.0, le=120.0)

    @field_validator("authorized_file_roots", "knowledge_roots")
    @classmethod
    def unique_paths(cls, value: list[Path]) -> list[Path]:
        keys = [str(path).casefold() for path in value]
        if len(keys) != len(set(keys)):
            raise ValueError("目录列表不能重复")
        return value

    @model_validator(mode="after")
    def unique_voices(self) -> "DesktopSettingsUpdate":
        ids = [voice.id for voice in self.zipvoice_voices]
        if len(ids) != len(set(ids)):
            raise ValueError("音色 ID 必须唯一")
        if self.tts_provider == "zipvoice":
            if not ids:
                raise ValueError("启用 ZipVoice 时至少需要一个音色")
            if self.zipvoice_default_voice_id not in ids:
                raise ValueError("默认音色必须存在于音色预设中")
        return self


class DesktopSettingsView(DesktopSettingsUpdate):
    locked_fields: list[str] = Field(default_factory=list)
    supervised: bool = False
    ollama_models: list[str] = Field(default_factory=list)
    knowledge_index: dict[str, object] = Field(default_factory=dict)


class RestartStatus(BaseModel):
    state: str
    supervised: bool
    requested_at: str | None = None
    completed_at: str | None = None
    message: str = ""
    rollback_performed: bool = False


__all__ = ["DesktopSettingsUpdate", "DesktopSettingsView", "DesktopVoicePreset", "RestartStatus"]
