"""Typed configuration loaded once from environment and .env."""

import json
import os
from ipaddress import ip_address
from functools import lru_cache
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _split_paths(value: object) -> object:
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            decoded = None
        if isinstance(decoded, list):
            return decoded
        return [part.strip() for part in value.split(";") if part.strip()]
    return value


PathList = Annotated[list[Path], NoDecode, BeforeValidator(_split_paths)]


class ZipVoicePreset(BaseModel):
    """One selectable zero-shot reference voice."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    label: str = Field(..., min_length=1, max_length=40)
    reference_audio_path: Path
    reference_text: str = Field(..., min_length=1, max_length=1000)


def _application_root() -> Path:
    """Use an explicit portable root or the source checkout for local resources.

    The CLI is commonly launched from a shell shortcut or another working
    directory.  Relative defaults must still point at this checkout's
    ``demo_documents`` and persistent ``data`` directory rather than
    creating empty sibling directories under the caller's current directory.
    Portable distributions set ``AGENT_APP_ROOT`` so installed code and its
    relative configuration continue to follow the distribution after it moves.
    """

    configured_root = os.getenv("AGENT_APP_ROOT", "").strip()
    if configured_root:
        candidate = Path(configured_root).expanduser().resolve()
        if not candidate.is_dir():
            raise ValueError(f"AGENT_APP_ROOT must reference an existing directory: {candidate}")
        return candidate

    package_root = Path(__file__).resolve().parents[2]
    if (package_root / "pyproject.toml").is_file() and (package_root / "agent_platform").is_dir():
        return package_root
    return Path.cwd()


def _resolve_local_path(value: Path, root: Path) -> Path:
    return value if value.is_absolute() else root / value


class Settings(BaseSettings):
    """Application settings with safe local defaults."""

    model_config = SettingsConfigDict(
        env_file=None,
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    def __init__(self, **values: object) -> None:
        # Resolve the default env file at instantiation time so a portable
        # launcher can set AGENT_APP_ROOT after this module has been imported.
        values.setdefault("_env_file", _application_root() / ".env")
        super().__init__(**values)

    model_provider: str = Field(default="mock", validation_alias="MODEL_PROVIDER")
    model_base_url: str = Field(default="https://api.example.com/v1", validation_alias="MODEL_BASE_URL")
    model_name: str = Field(default="qwen2.5-3b-instruct", validation_alias="MODEL_NAME")
    model_digest: str = Field(default="unknown", validation_alias="MODEL_DIGEST")
    model_api_key: str = Field(default="", validation_alias="MODEL_API_KEY")
    model_timeout_seconds: float = Field(default=30.0, gt=0, validation_alias="MODEL_TIMEOUT_SECONDS")

    ollama_base_url: str = Field(default="http://127.0.0.1:11434", validation_alias="OLLAMA_BASE_URL")
    ollama_timeout_seconds: float = Field(default=120.0, gt=0, validation_alias="OLLAMA_TIMEOUT_SECONDS")
    ollama_thinking_enabled: bool = Field(default=False, validation_alias="OLLAMA_THINKING_ENABLED")
    ollama_keep_alive: str = Field(default="10m", validation_alias="OLLAMA_KEEP_ALIVE")
    ollama_max_new_tokens: int = Field(default=512, ge=1, le=8192, validation_alias="OLLAMA_MAX_NEW_TOKENS")

    rkllm_server_url: str = Field(default="http://127.0.0.1:8080/v1", validation_alias="RKLLM_SERVER_URL")
    rkllm_model_name: str = Field(default="rkllm", validation_alias="RKLLM_MODEL_NAME")
    rkllm_model_digest: str = Field(default="unknown", validation_alias="RKLLM_MODEL_DIGEST")
    rkllm_timeout_seconds: float = Field(default=30.0, gt=0, validation_alias="RKLLM_TIMEOUT_SECONDS")
    rkllm_queue_timeout_seconds: float = Field(default=2.0, gt=0, validation_alias="RKLLM_QUEUE_TIMEOUT_SECONDS")
    rkllm_max_concurrency: int = Field(default=1, ge=1, le=8, validation_alias="RKLLM_MAX_CONCURRENCY")
    rkllm_max_context: int = Field(default=4096, ge=512, le=32768, validation_alias="RKLLM_MAX_CONTEXT")
    rkllm_max_new_tokens: int = Field(default=512, ge=1, le=8192, validation_alias="RKLLM_MAX_NEW_TOKENS")

    llamacpp_server_url: str = Field(default="http://127.0.0.1:8080/v1", validation_alias="LLAMACPP_SERVER_URL")
    llamacpp_model_name: str = Field(default="local-model", validation_alias="LLAMACPP_MODEL_NAME")
    llamacpp_model_digest: str = Field(default="unknown", validation_alias="LLAMACPP_MODEL_DIGEST")
    llamacpp_timeout_seconds: float = Field(default=120.0, gt=0, validation_alias="LLAMACPP_TIMEOUT_SECONDS")
    llamacpp_queue_timeout_seconds: float = Field(default=2.0, gt=0, validation_alias="LLAMACPP_QUEUE_TIMEOUT_SECONDS")
    llamacpp_threads: int = Field(default=4, ge=1, le=32, validation_alias="LLAMACPP_THREADS")
    llamacpp_context_size: int = Field(default=2048, ge=512, le=32768, validation_alias="LLAMACPP_CONTEXT_SIZE")
    llamacpp_max_tokens: int = Field(default=256, ge=1, le=8192, validation_alias="LLAMACPP_MAX_TOKENS")
    llamacpp_batch_size: int = Field(default=256, ge=1, le=4096, validation_alias="LLAMACPP_BATCH_SIZE")
    llamacpp_parallel: int = Field(default=1, ge=1, le=8, validation_alias="LLAMACPP_PARALLEL")

    model_fallback_enabled: bool = Field(default=False, validation_alias="MODEL_FALLBACK_ENABLED")
    model_fallback_base_url: str = Field(
        default="https://api.example.com/v1", validation_alias="MODEL_FALLBACK_BASE_URL"
    )
    model_fallback_name: str = Field(default="qwen2.5-3b-instruct", validation_alias="MODEL_FALLBACK_NAME")
    model_fallback_api_key: str = Field(default="", validation_alias="MODEL_FALLBACK_API_KEY")
    model_fallback_timeout_seconds: float = Field(
        default=30.0, gt=0, validation_alias="MODEL_FALLBACK_TIMEOUT_SECONDS"
    )

    host: str = Field(default="127.0.0.1", validation_alias="AGENT_HOST")
    port: int = Field(default=8000, ge=1, le=65535, validation_alias="AGENT_PORT")
    developer_password: str = Field(default="", repr=False, validation_alias="DEVELOPER_PASSWORD")
    database_path: Path = Field(default=Path("data/agent_platform.db"), validation_alias="AGENT_DATABASE_PATH")
    audit_dir: Path = Field(default=Path("logs/audit"), validation_alias="AGENT_AUDIT_DIR")
    retention_days: int = Field(default=30, ge=1, validation_alias="AGENT_RETENTION_DAYS")
    file_open_enabled: bool = Field(default=False, validation_alias="AGENT_FILE_OPEN_ENABLED")
    authorized_file_roots: PathList = Field(default_factory=lambda: [Path("data/documents"), Path("demo_documents")], validation_alias="AGENT_AUTHORIZED_FILE_ROOTS")
    knowledge_roots: PathList = Field(default_factory=lambda: [Path("data/documents"), Path("demo_documents")], validation_alias="AGENT_KNOWLEDGE_ROOTS")
    document_roots: PathList = Field(
        default_factory=lambda: [Path("data/documents"), Path("demo_documents")],
        validation_alias="AGENT_DOCUMENT_ROOTS",
    )
    meeting_output_dir: Path = Field(default=Path("data/meeting_notes"), validation_alias="AGENT_MEETING_OUTPUT_DIR")
    tts_provider: str = Field(default="disabled", validation_alias="TTS_PROVIDER")
    tts_output_dir: Path = Field(default=Path("data/tts"), validation_alias="TTS_OUTPUT_DIR")
    tts_max_chars: int = Field(default=2000, ge=1, le=10000, validation_alias="TTS_MAX_CHARS")
    tts_keep_versions: int = Field(default=3, ge=1, le=20, validation_alias="TTS_KEEP_VERSIONS")
    zipvoice_model_dir: Path = Field(default=Path("models/zipvoice"), validation_alias="ZIPVOICE_MODEL_DIR")
    zipvoice_vocoder_path: Path = Field(default=Path("models/zipvoice/vocos_24khz.onnx"), validation_alias="ZIPVOICE_VOCODER_PATH")
    zipvoice_reference_audio_path: Path = Field(default=Path("models/zipvoice/reference.wav"), validation_alias="ZIPVOICE_REFERENCE_AUDIO_PATH")
    zipvoice_reference_text: str = Field(default="", validation_alias="ZIPVOICE_REFERENCE_TEXT")
    zipvoice_voices: list[ZipVoicePreset] = Field(default_factory=list, validation_alias="ZIPVOICE_VOICES")
    zipvoice_default_voice_id: str = Field(default="default", validation_alias="ZIPVOICE_DEFAULT_VOICE_ID")
    zipvoice_num_threads: int = Field(default=4, ge=1, le=32, validation_alias="ZIPVOICE_NUM_THREADS")
    zipvoice_speed: float = Field(default=1.0, ge=0.5, le=2.0, validation_alias="ZIPVOICE_SPEED")
    zipvoice_num_steps: int = Field(default=4, ge=1, le=16, validation_alias="ZIPVOICE_NUM_STEPS")
    voice_enabled: bool = Field(default=False, validation_alias="VOICE_ENABLED")
    voice_input_device: str = Field(default="", validation_alias="VOICE_INPUT_DEVICE")
    voice_model_dir: Path = Field(
        default=Path("models/faster-whisper-small"), validation_alias="VOICE_MODEL_DIR"
    )
    voice_cpu_threads: int = Field(default=8, ge=1, le=32, validation_alias="VOICE_CPU_THREADS")
    voice_num_workers: int = Field(default=1, ge=1, le=4, validation_alias="VOICE_NUM_WORKERS")
    voice_beam_size: int = Field(default=3, ge=1, le=10, validation_alias="VOICE_BEAM_SIZE")
    voice_vad_enabled: bool = Field(default=True, validation_alias="VOICE_VAD_ENABLED")
    voice_max_recording_seconds: float = Field(
        default=30.0, ge=1.0, le=120.0, validation_alias="VOICE_MAX_RECORDING_SECONDS"
    )
    voice_min_recording_seconds: float = Field(
        default=0.4, ge=0.1, le=5.0, validation_alias="VOICE_MIN_RECORDING_SECONDS"
    )
    voice_silence_dbfs: float = Field(
        default=-50.0, ge=-90.0, le=-10.0, validation_alias="VOICE_SILENCE_DBFS"
    )
    voice_transcription_timeout_seconds: float = Field(
        default=60.0, gt=0, le=300.0, validation_alias="VOICE_TRANSCRIPTION_TIMEOUT_SECONDS"
    )
    timezone: str = Field(default="Asia/Shanghai", validation_alias="AGENT_TIMEZONE")
    network_available: bool = Field(default=True, validation_alias="AGENT_NETWORK_AVAILABLE")
    resource_mode: str = Field(default="normal", validation_alias="AGENT_RESOURCE_MODE")
    idempotency_ttl_seconds: int = Field(default=3600, ge=1, validation_alias="AGENT_IDEMPOTENCY_TTL_SECONDS")
    audit_flush_size: int = Field(default=10, ge=1, le=1000, validation_alias="AGENT_AUDIT_FLUSH_SIZE")

    @model_validator(mode="after")
    def resolve_runtime_paths(self) -> "Settings":
        """Resolve relative local paths once against the application root."""

        root = _application_root()
        # The new unified source wins when configured. Explicit legacy values
        # remain useful for older deployments and are merged only as fallback.
        if not os.getenv("AGENT_DOCUMENT_ROOTS", "").strip() and (
            "authorized_file_roots" in self.model_fields_set
            or "knowledge_roots" in self.model_fields_set
            or os.getenv("AGENT_AUTHORIZED_FILE_ROOTS", "").strip()
            or os.getenv("AGENT_KNOWLEDGE_ROOTS", "").strip()
        ):
            merged: list[Path] = []
            for candidate in [*self.authorized_file_roots, *self.knowledge_roots]:
                if candidate not in merged:
                    merged.append(candidate)
            self.document_roots = merged
        self.database_path = _resolve_local_path(self.database_path, root)
        self.audit_dir = _resolve_local_path(self.audit_dir, root)
        self.authorized_file_roots = [
            _resolve_local_path(path, root) for path in self.authorized_file_roots
        ]
        self.knowledge_roots = [_resolve_local_path(path, root) for path in self.knowledge_roots]
        self.document_roots = [_resolve_local_path(path, root) for path in self.document_roots]
        self.meeting_output_dir = _resolve_local_path(self.meeting_output_dir, root)
        self.tts_output_dir = _resolve_local_path(self.tts_output_dir, root)
        self.zipvoice_model_dir = _resolve_local_path(self.zipvoice_model_dir, root)
        self.zipvoice_vocoder_path = _resolve_local_path(self.zipvoice_vocoder_path, root)
        self.zipvoice_reference_audio_path = _resolve_local_path(self.zipvoice_reference_audio_path, root)
        self.voice_model_dir = _resolve_local_path(self.voice_model_dir, root)
        self.zipvoice_voices = [
            voice.model_copy(
                update={"reference_audio_path": _resolve_local_path(voice.reference_audio_path, root)}
            )
            for voice in self.zipvoice_voices
        ]
        host = self.host.strip().strip("[]")
        try:
            loopback = ip_address(host).is_loopback
        except ValueError:
            loopback = host.casefold() == "localhost"
        if not loopback and not self.developer_password:
            raise ValueError("DEVELOPER_PASSWORD is required when AGENT_HOST is not a loopback address")
        return self

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        ZoneInfo(value)
        return value

    @field_validator("tts_provider")
    @classmethod
    def valid_tts_provider(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"disabled", "zipvoice"}:
            raise ValueError("TTS_PROVIDER must be disabled or zipvoice")
        return normalized


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide immutable configuration snapshot."""

    return Settings()


__all__ = ["Settings", "ZipVoicePreset", "get_settings"]
