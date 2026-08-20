from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import httpx

from agent_platform.api.server import create_app
from agent_platform.config import Settings
from agent_platform.core.errors import (
    RecordingTooShortError,
    SilentRecordingError,
    VoiceDeviceUnavailableError,
    VoiceServiceBusyError,
    VoiceTranscriptionTimeoutError,
)
from agent_platform.core.voice_input import VoiceInputService, normalize_transcript
from agent_platform.models.voice import VoiceDevice
from ruoyi_support import enable_gateway


class _Stream:
    def __init__(self, callback, chunks: list[bytes]) -> None:
        self.callback = callback
        self.chunks = chunks
        self.closed = False

    def start(self):
        for chunk in self.chunks:
            self.callback(chunk)

    def stop(self):
        return None

    def close(self):
        self.closed = True


class _Backend:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.stream = None

    def devices(self):
        return [VoiceDevice(id="0", name="Test microphone", channels=1, default=True)]

    def open_stream(self, device, callback):
        self.stream = _Stream(callback, self.chunks)
        return self.stream


class _Transcriber:
    def __init__(self, text: str = "文件處理完成 項目周報", delay: float = 0.0) -> None:
        self.text = text
        self.delay = delay
        self.samples = None

    def transcribe(self, samples: bytes) -> str:
        self.samples = samples
        if self.delay:
            import time

            time.sleep(self.delay)
        return self.text


def _settings(tmp_path: Path, **updates) -> Settings:
    model = tmp_path / "faster-whisper-small"
    model.mkdir(exist_ok=True)
    files = tmp_path / "files"
    knowledge = tmp_path / "knowledge"
    files.mkdir(exist_ok=True)
    knowledge.mkdir(exist_ok=True)
    values = {
        "_env_file": None,
        "model_provider": "mock",
        "database_path": tmp_path / "agent.db",
        "audit_dir": tmp_path / "audit",
        "authorized_file_roots": [files],
        "knowledge_roots": [knowledge],
        "meeting_output_dir": tmp_path / "meeting",
        "voice_enabled": True,
        "voice_model_dir": model,
        "voice_min_recording_seconds": 0.1,
        "voice_silence_dbfs": -70,
        "voice_transcription_timeout_seconds": 1,
    }
    values.update(updates)
    return Settings(**values)


def _tone(seconds: float = 0.2, sample: int = 5000) -> bytes:
    return int(sample).to_bytes(2, "little", signed=True) * int(16000 * seconds)


@pytest.mark.asyncio
async def test_recording_transcribes_and_releases_pcm(tmp_path: Path) -> None:
    backend = _Backend([_tone()])
    transcriber = _Transcriber()
    service = VoiceInputService(_settings(tmp_path), backend=backend, transcriber=transcriber)
    started = service.start("one")
    assert started.state == "recording"
    assert service.status().active_recording_id == started.id

    finished = await service.stop(started.id, "one")

    assert finished.state == "completed"
    assert finished.transcript == "文件处理完成 项目周报"
    assert service._active is None
    assert backend.stream.closed is True
    assert transcriber.samples == bytearray()


def test_only_one_recording_and_session_isolation(tmp_path: Path) -> None:
    service = VoiceInputService(_settings(tmp_path), backend=_Backend([_tone()]), transcriber=_Transcriber())
    started = service.start("one")
    with pytest.raises(VoiceServiceBusyError):
        service.start("one")
    with pytest.raises(VoiceDeviceUnavailableError):
        service.cancel(started.id, "two")
    cancelled = service.cancel(started.id, "one")
    assert cancelled.state == "cancelled"
    assert service._active is None


@pytest.mark.asyncio
async def test_short_silent_and_timeout_errors_release_pcm(tmp_path: Path) -> None:
    short = VoiceInputService(_settings(tmp_path), backend=_Backend([_tone(0.02)]), transcriber=_Transcriber())
    recording = short.start("one")
    with pytest.raises(RecordingTooShortError):
        await short.stop(recording.id, "one")
    assert short._active is None

    silent = VoiceInputService(
        _settings(tmp_path, voice_silence_dbfs=-50),
        backend=_Backend([_tone(sample=0)]),
        transcriber=_Transcriber(),
    )
    recording = silent.start("one")
    with pytest.raises(SilentRecordingError):
        await silent.stop(recording.id, "one")
    assert silent._active is None

    timeout = VoiceInputService(
        _settings(tmp_path, voice_transcription_timeout_seconds=0.01),
        backend=_Backend([_tone()]),
        transcriber=_Transcriber(delay=0.1),
    )
    recording = timeout.start("one")
    with pytest.raises(VoiceTranscriptionTimeoutError):
        await timeout.stop(recording.id, "one")
    assert timeout._active is None


def test_transcript_normalization_is_simplified_and_compact() -> None:
    assert normalize_transcript("  項目\n會議  ") == "项目 会议"
    assert normalize_transcript("创建明天下午两点项目立会") == "创建明天下午两点项目例会"


@pytest.mark.asyncio
async def test_voice_api_enforces_browser_session(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings)
    backend = _Backend([_tone()])
    service = VoiceInputService(settings, backend=backend, transcriber=_Transcriber("一加一等于二"))
    async with app.router.lifespan_context(app):
        gateway = enable_gateway(app)
        app.state.container.voice = service
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", headers=gateway.headers()
        ) as owner, httpx.AsyncClient(
            transport=transport, base_url="http://test", headers=gateway.headers(username="other", user_id=200)
        ) as other:
            started = await owner.post("/voice/recordings")
            assert started.status_code == 201
            recording_id = started.json()["id"]
            forbidden = await other.post(f"/voice/recordings/{recording_id}/cancel")
            assert forbidden.status_code == 400
            assert forbidden.json()["code"] == "voice_device_unavailable"
            stopped = await owner.post(f"/voice/recordings/{recording_id}/stop")
            assert stopped.status_code == 200
            assert stopped.json()["transcript"] == "一加一等于二"
