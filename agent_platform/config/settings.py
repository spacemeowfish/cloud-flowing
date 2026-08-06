"""Typed configuration loaded once from environment and .env."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

from pydantic import BeforeValidator, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _split_paths(value: object) -> object:
    if isinstance(value, str):
        return [part.strip() for part in value.split(";") if part.strip()]
    return value


PathList = Annotated[list[Path], BeforeValidator(_split_paths)]


class Settings(BaseSettings):
    """Application settings with safe local defaults."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", populate_by_name=True
    )

    model_provider: str = Field(default="mock", validation_alias="MODEL_PROVIDER")
    model_base_url: str = Field(default="https://api.example.com/v1", validation_alias="MODEL_BASE_URL")
    model_name: str = Field(default="qwen2.5-3b-instruct", validation_alias="MODEL_NAME")
    model_digest: str = Field(default="unknown", validation_alias="MODEL_DIGEST")
    model_api_key: str = Field(default="", validation_alias="MODEL_API_KEY")
    model_timeout_seconds: float = Field(default=30.0, gt=0, validation_alias="MODEL_TIMEOUT_SECONDS")

    rkllm_server_url: str = Field(default="http://127.0.0.1:8080/v1", validation_alias="RKLLM_SERVER_URL")
    rkllm_model_name: str = Field(default="rkllm", validation_alias="RKLLM_MODEL_NAME")
    rkllm_model_digest: str = Field(default="unknown", validation_alias="RKLLM_MODEL_DIGEST")
    rkllm_timeout_seconds: float = Field(default=30.0, gt=0, validation_alias="RKLLM_TIMEOUT_SECONDS")
    rkllm_queue_timeout_seconds: float = Field(default=2.0, gt=0, validation_alias="RKLLM_QUEUE_TIMEOUT_SECONDS")
    rkllm_max_concurrency: int = Field(default=1, ge=1, le=8, validation_alias="RKLLM_MAX_CONCURRENCY")
    rkllm_max_context: int = Field(default=4096, ge=512, le=32768, validation_alias="RKLLM_MAX_CONTEXT")
    rkllm_max_new_tokens: int = Field(default=512, ge=1, le=8192, validation_alias="RKLLM_MAX_NEW_TOKENS")

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
    database_path: Path = Field(default=Path("data/agent_platform.db"), validation_alias="AGENT_DATABASE_PATH")
    audit_dir: Path = Field(default=Path("logs/audit"), validation_alias="AGENT_AUDIT_DIR")
    retention_days: int = Field(default=30, ge=1, validation_alias="AGENT_RETENTION_DAYS")
    file_open_enabled: bool = Field(default=False, validation_alias="AGENT_FILE_OPEN_ENABLED")
    authorized_file_roots: PathList = Field(default_factory=lambda: [Path("data/authorized_files"), Path("demo_files")], validation_alias="AGENT_AUTHORIZED_FILE_ROOTS")
    knowledge_roots: PathList = Field(default_factory=lambda: [Path("data/knowledge"), Path("demo_docs")], validation_alias="AGENT_KNOWLEDGE_ROOTS")
    meeting_output_dir: Path = Field(default=Path("data/meeting_notes"), validation_alias="AGENT_MEETING_OUTPUT_DIR")
    timezone: str = Field(default="Asia/Shanghai", validation_alias="AGENT_TIMEZONE")
    network_available: bool = Field(default=True, validation_alias="AGENT_NETWORK_AVAILABLE")
    resource_mode: str = Field(default="normal", validation_alias="AGENT_RESOURCE_MODE")
    idempotency_ttl_seconds: int = Field(default=3600, ge=1, validation_alias="AGENT_IDEMPOTENCY_TTL_SECONDS")
    audit_flush_size: int = Field(default=10, ge=1, le=1000, validation_alias="AGENT_AUDIT_FLUSH_SIZE")

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        ZoneInfo(value)
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide immutable configuration snapshot."""

    return Settings()


__all__ = ["Settings", "get_settings"]
