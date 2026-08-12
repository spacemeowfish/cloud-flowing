"""Validated, atomic project .env updates for the local desktop workbench."""

from __future__ import annotations

import json
import os
import tempfile
import wave
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import httpx

from agent_platform.config import Settings
from agent_platform.config.settings import _application_root
from agent_platform.core.errors import ConfigurationError
from agent_platform.models.admin import DesktopSettingsUpdate, DesktopSettingsView, RestartStatus


FIELD_TO_ENV = {
    "model_provider": "MODEL_PROVIDER",
    "model_name": "MODEL_NAME",
    "ollama_base_url": "OLLAMA_BASE_URL",
    "file_open_enabled": "AGENT_FILE_OPEN_ENABLED",
    "authorized_file_roots": "AGENT_AUTHORIZED_FILE_ROOTS",
    "knowledge_roots": "AGENT_KNOWLEDGE_ROOTS",
    "tts_provider": "TTS_PROVIDER",
    "zipvoice_model_dir": "ZIPVOICE_MODEL_DIR",
    "zipvoice_vocoder_path": "ZIPVOICE_VOCODER_PATH",
    "zipvoice_num_threads": "ZIPVOICE_NUM_THREADS",
    "zipvoice_speed": "ZIPVOICE_SPEED",
    "zipvoice_default_voice_id": "ZIPVOICE_DEFAULT_VOICE_ID",
    "zipvoice_voices": "ZIPVOICE_VOICES",
    "voice_enabled": "VOICE_ENABLED",
    "voice_input_device": "VOICE_INPUT_DEVICE",
    "voice_model_dir": "VOICE_MODEL_DIR",
    "voice_cpu_threads": "VOICE_CPU_THREADS",
    "voice_num_workers": "VOICE_NUM_WORKERS",
    "voice_beam_size": "VOICE_BEAM_SIZE",
    "voice_vad_enabled": "VOICE_VAD_ENABLED",
    "voice_max_recording_seconds": "VOICE_MAX_RECORDING_SECONDS",
}


class RestartController(Protocol):
    @property
    def supervised(self) -> bool: ...

    def request_restart(self, backup_path: Path | None) -> None: ...

    def status(self) -> RestartStatus: ...


class PassiveRestartController:
    supervised = False

    def __init__(self) -> None:
        self._status = RestartStatus(
            state="manual_restart_required",
            supervised=False,
            message="当前由 serve 启动，请手动重启服务应用新配置",
        )

    def request_restart(self, backup_path: Path | None) -> None:
        self._status.requested_at = datetime.now(UTC).isoformat()

    def status(self) -> RestartStatus:
        return self._status.model_copy(deep=True)


class DesktopSettingsService:
    def __init__(
        self,
        settings: Settings,
        restart_controller: RestartController,
        *,
        env_path: Path | None = None,
    ) -> None:
        self._settings = settings
        self._restart = restart_controller
        self._env_path = env_path or (_application_root() / ".env")

    @property
    def locked_fields(self) -> list[str]:
        return sorted(field for field, env in FIELD_TO_ENV.items() if env in os.environ)

    async def view(self, *, include_models: bool = True) -> DesktopSettingsView:
        settings = self._settings
        models = await self.discover_ollama_models() if include_models else []
        documents = sum(
            1
            for root in settings.knowledge_roots
            if root.is_dir()
            for path in root.rglob("*")
            if path.is_file() and path.suffix.casefold() in {".txt", ".md", ".docx"}
        )
        index_path = settings.database_path.with_name("knowledge.db")
        return DesktopSettingsView(
            model_provider=settings.model_provider,
            model_name=settings.model_name,
            ollama_base_url=settings.ollama_base_url,
            file_open_enabled=settings.file_open_enabled,
            authorized_file_roots=list(settings.authorized_file_roots),
            knowledge_roots=list(settings.knowledge_roots),
            tts_provider=settings.tts_provider,
            zipvoice_model_dir=settings.zipvoice_model_dir,
            zipvoice_vocoder_path=settings.zipvoice_vocoder_path,
            zipvoice_num_threads=settings.zipvoice_num_threads,
            zipvoice_speed=settings.zipvoice_speed,
            zipvoice_default_voice_id=settings.zipvoice_default_voice_id,
            zipvoice_voices=[
                {
                    "id": voice.id,
                    "name": voice.label,
                    "reference_wav": voice.reference_audio_path,
                    "reference_text": voice.reference_text,
                }
                for voice in settings.zipvoice_voices
            ],
            voice_enabled=settings.voice_enabled,
            voice_input_device=settings.voice_input_device,
            voice_model_dir=settings.voice_model_dir,
            voice_cpu_threads=settings.voice_cpu_threads,
            voice_num_workers=settings.voice_num_workers,
            voice_beam_size=settings.voice_beam_size,
            voice_vad_enabled=settings.voice_vad_enabled,
            voice_max_recording_seconds=settings.voice_max_recording_seconds,
            locked_fields=self.locked_fields,
            supervised=self._restart.supervised,
            ollama_models=models,
            knowledge_index={
                "document_count": documents,
                "index_exists": index_path.is_file(),
                "index_path": str(index_path),
            },
        )

    async def discover_ollama_models(self, base_url: str | None = None) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(f"{(base_url or self._settings.ollama_base_url).rstrip('/')}/api/tags")
                response.raise_for_status()
            payload = response.json()
            return sorted(
                str(model.get("name", "")).strip()
                for model in payload.get("models", [])
                if str(model.get("name", "")).strip()
            )
        except (httpx.HTTPError, ValueError, TypeError):
            return []

    async def update(self, payload: DesktopSettingsUpdate) -> DesktopSettingsView:
        await self._validate(payload)
        values = {field: getattr(payload, field) for field in type(payload).model_fields}
        updates = {
            FIELD_TO_ENV[field]: self._serialize(field, value)
            for field, value in values.items()
            if field in FIELD_TO_ENV and field not in self.locked_fields
        }
        backup = self._write_env(updates)
        try:
            proposed = Settings(_env_file=self._env_path)
        except Exception:
            restore_env_backup(backup, env_path=self._env_path)
            raise
        self._restart.request_restart(backup)
        return await DesktopSettingsService(
            proposed, self._restart, env_path=self._env_path
        ).view(include_models=False)

    async def _validate(self, payload: DesktopSettingsUpdate) -> None:
        for path in [*payload.authorized_file_roots, *payload.knowledge_roots]:
            if not path.expanduser().is_dir():
                raise ConfigurationError(f"目录不存在：{path}")
        if payload.model_provider == "ollama":
            models = await self.discover_ollama_models(payload.ollama_base_url)
            if payload.model_name not in models:
                raise ConfigurationError(f"Ollama 模型未安装或服务不可用：{payload.model_name}")
        if payload.tts_provider == "zipvoice":
            if not payload.zipvoice_model_dir.is_dir():
                raise ConfigurationError(f"ZipVoice 模型目录不存在：{payload.zipvoice_model_dir}")
            if not payload.zipvoice_vocoder_path.is_file():
                raise ConfigurationError(f"ZipVoice vocoder 不存在：{payload.zipvoice_vocoder_path}")
            for voice in payload.zipvoice_voices:
                self._validate_wav(voice.reference_wav)
                if not voice.reference_text.strip():
                    raise ConfigurationError(f"音色 {voice.id} 缺少逐字文本")
        if payload.voice_enabled and not payload.voice_model_dir.is_dir():
            raise ConfigurationError(f"Faster-Whisper 模型目录不存在：{payload.voice_model_dir}")

    @staticmethod
    def _validate_wav(path: Path) -> None:
        if not path.is_file() or path.suffix.casefold() != ".wav":
            raise ConfigurationError(f"音色参考文件必须是存在的 WAV：{path}")
        try:
            with wave.open(str(path), "rb") as source:
                if source.getnchannels() != 1 or source.getsampwidth() not in {2, 3}:
                    raise ConfigurationError(f"WAV 必须为单声道 PCM16/PCM24：{path}")
                if source.getframerate() <= 0 or source.getnframes() <= 0:
                    raise ConfigurationError(f"WAV 内容为空：{path}")
        except (wave.Error, EOFError) as exc:
            raise ConfigurationError(f"无法读取 WAV：{path}") from exc

    @staticmethod
    def _serialize(field: str, value: object) -> str:
        if field in {"authorized_file_roots", "knowledge_roots"}:
            return json.dumps([str(path) for path in value], ensure_ascii=False)
        if field == "zipvoice_voices":
            return json.dumps(
                [
                    {
                        "id": voice.id,
                        "label": voice.name,
                        "reference_audio_path": str(voice.reference_wav),
                        "reference_text": voice.reference_text,
                    }
                    for voice in value
                ],
                ensure_ascii=False,
                separators=(",", ":"),
            )
        if isinstance(value, bool):
            return str(value).lower()
        return str(value)

    def _write_env(self, updates: dict[str, str]) -> Path | None:
        original = self._env_path.read_text(encoding="utf-8") if self._env_path.is_file() else ""
        backup_dir = self._env_path.parent / ".env.backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        backup = backup_dir / f"{stamp}.env"
        backup.write_text(original, encoding="utf-8")
        backups = sorted(backup_dir.glob("*.env"), reverse=True)
        for stale in backups[5:]:
            stale.unlink()

        remaining = dict(updates)
        output: list[str] = []
        for line in original.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in line:
                output.append(line)
                continue
            key = line.split("=", 1)[0].strip()
            if key in remaining:
                output.append(f"{key}={remaining.pop(key)}")
            else:
                output.append(line)
        if output and remaining:
            output.append("")
        output.extend(f"{key}={value}" for key, value in remaining.items())
        content = "\n".join(output).rstrip() + "\n"
        self._env_path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(
            prefix=f".{self._env_path.name}.", suffix=".tmp", dir=self._env_path.parent
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._env_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return backup


def restore_env_backup(backup: Path | None, *, env_path: Path | None = None) -> bool:
    if backup is None or not backup.is_file():
        return False
    target = env_path or (_application_root() / ".env")
    content = backup.read_bytes()
    handle, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return True


__all__ = [
    "DesktopSettingsService",
    "FIELD_TO_ENV",
    "PassiveRestartController",
    "RestartController",
    "restore_env_backup",
]
