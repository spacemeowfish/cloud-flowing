"""Session-safe speech artifact generation for completed Agent tasks."""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import JsonValue

from agent_platform.core.errors import PermissionDeniedError, SpeechUnavailableError
from agent_platform.core.interfaces import SpeechSynthesizer
from agent_platform.core.task_api import TaskAPI
from agent_platform.models import SpeechArtifact, TaskRecord, TaskState


_WHITESPACE = re.compile(r"\s+")


class DisabledSpeechSynthesizer(SpeechSynthesizer):
    async def synthesize(self, text: str, voice_id: str | None = None):
        raise SpeechUnavailableError("TTS 未启用，请配置 TTS_PROVIDER=zipvoice")

    def status(self) -> dict[str, JsonValue]:
        return {
            "enabled": False,
            "provider": "disabled",
            "configured": False,
            "dependency_available": False,
            "ready": False,
            "model_loaded": False,
            "missing_resource_count": 0,
            "default_voice_id": None,
            "voices": [],
        }


class SpeechOutputService:
    """Generate immutable WAV versions without changing the source task."""

    def __init__(
        self,
        *,
        tasks: TaskAPI,
        synthesizer: SpeechSynthesizer,
        output_dir: Path,
        max_chars: int,
        keep_versions: int,
    ) -> None:
        self._tasks = tasks
        self._synthesizer = synthesizer
        self._output_dir = output_dir.resolve()
        self._max_chars = max_chars
        self._keep_versions = keep_versions
        self._locks: dict[UUID, asyncio.Lock] = {}

    def status(self) -> dict[str, JsonValue]:
        return self._synthesizer.status()

    async def create(self, task_id: UUID, session_id: str, voice_id: str | None = None) -> SpeechArtifact:
        task = await self._authorized_task(task_id, session_id)
        text = self._extract_text(task)
        if not text:
            raise SpeechUnavailableError("该任务没有可朗读的文本结果")
        if len(text) > self._max_chars:
            raise SpeechUnavailableError(f"可朗读文本不能超过 {self._max_chars} 个字符")

        lock = self._locks.setdefault(task_id, asyncio.Lock())
        async with lock:
            audio = await self._synthesizer.synthesize(text, voice_id)
            version_id = uuid4()
            directory = self._output_dir / str(task_id)
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f"{version_id}.wav"
            await asyncio.to_thread(path.write_bytes, audio.wav_bytes)
            await asyncio.to_thread(self._remove_old_versions, directory, path)
        return SpeechArtifact(
            task_id=task_id,
            version_id=version_id,
            voice_id=audio.voice_id,
            voice_label=audio.voice_label,
            audio_url=f"/tasks/{task_id}/speech/{version_id}",
            sample_rate=audio.sample_rate,
            duration_seconds=audio.duration_seconds,
            created_at=datetime.now(UTC),
        )

    async def path_for(self, task_id: UUID, version_id: UUID, session_id: str) -> Path:
        await self._authorized_task(task_id, session_id)
        path = self._output_dir / str(task_id) / f"{version_id}.wav"
        if not path.is_file():
            raise SpeechUnavailableError("语音版本不存在或已经过期")
        return path

    async def close(self) -> None:
        await self._synthesizer.close()

    async def _authorized_task(self, task_id: UUID, session_id: str) -> TaskRecord:
        task = await self._tasks.get(task_id)
        if task.session_id != session_id:
            raise PermissionDeniedError("Task belongs to another session")
        if task.state != TaskState.COMPLETED:
            raise SpeechUnavailableError("只能朗读已完成任务的结果")
        return task

    @staticmethod
    def _extract_text(task: TaskRecord) -> str:
        result = task.result or {}
        output = result.get("output")
        if isinstance(output, dict):
            for key in ("answer", "text", "message"):
                value = output.get(key)
                if isinstance(value, str) and value.strip():
                    return _WHITESPACE.sub(" ", value).strip()
        summary = result.get("output_summary")
        if isinstance(summary, str) and summary.strip():
            return _WHITESPACE.sub(" ", summary).strip()
        return ""

    def _remove_old_versions(self, directory: Path, keep: Path) -> None:
        versions = sorted(
            directory.glob("*.wav"),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
        previous = [path for path in versions if path != keep]
        retained = {keep, *previous[: self._keep_versions - 1]}
        for path in versions:
            if path not in retained:
                path.unlink(missing_ok=True)


__all__ = ["DisabledSpeechSynthesizer", "SpeechOutputService"]
