"""In-memory microphone capture and Faster-Whisper transcription."""

from __future__ import annotations

import asyncio
import importlib.util
import math
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID, uuid4

from agent_platform.config import Settings
from agent_platform.core.errors import (
    NoMicrophoneError,
    RecordingTooShortError,
    SilentRecordingError,
    VoiceDeviceUnavailableError,
    VoiceModelMissingError,
    VoiceServiceBusyError,
    VoiceTranscriptionTimeoutError,
)
from agent_platform.models.voice import VoiceDevice, VoiceRecording, VoiceStatus


SAMPLE_RATE = 16_000
SAMPLE_WIDTH = 2


class InputStream(Protocol):
    def start(self) -> object: ...

    def stop(self) -> object: ...

    def close(self) -> object: ...


class AudioBackend(Protocol):
    def devices(self) -> list[VoiceDevice]: ...

    def open_stream(self, device: str, callback: Callable[[bytes], None]) -> InputStream: ...


class Transcriber(Protocol):
    def transcribe(self, samples: bytes | bytearray) -> str: ...


class SoundDeviceBackend:
    def _module(self):
        try:
            import sounddevice
        except (ImportError, OSError) as exc:
            raise NoMicrophoneError("未安装 sounddevice 或 PortAudio 不可用") from exc
        return sounddevice

    def devices(self) -> list[VoiceDevice]:
        sounddevice = self._module()
        try:
            devices = sounddevice.query_devices()
            default_input = sounddevice.default.device[0]
        except Exception as exc:
            raise VoiceDeviceUnavailableError(f"无法读取麦克风设备：{exc}") from exc
        result = []
        for index, item in enumerate(devices):
            channels = int(item.get("max_input_channels", 0))
            if channels > 0:
                result.append(
                    VoiceDevice(
                        id=str(index),
                        name=str(item.get("name", f"Input {index}")),
                        channels=channels,
                        default=index == default_input,
                    )
                )
        if not result:
            raise NoMicrophoneError("未检测到可用麦克风")
        return result

    def open_stream(self, device: str, callback: Callable[[bytes], None]) -> InputStream:
        sounddevice = self._module()
        selected: int | str | None = None
        if device.strip():
            selected = int(device) if device.isdigit() else device

        def on_audio(indata, frames, time_info, status) -> None:
            callback(bytes(indata))

        try:
            return sounddevice.RawInputStream(
                samplerate=SAMPLE_RATE,
                blocksize=1600,
                device=selected,
                channels=1,
                dtype="int16",
                callback=on_audio,
            )
        except Exception as exc:
            raise VoiceDeviceUnavailableError(f"麦克风设备不可用：{exc}") from exc


class FasterWhisperTranscriber:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._model: Any | None = None
        self._lock = threading.Lock()

    def _load(self):
        if not self._settings.voice_model_dir.is_dir():
            raise VoiceModelMissingError(f"Faster-Whisper 模型不存在：{self._settings.voice_model_dir}")
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise VoiceModelMissingError("未安装 faster-whisper 可选依赖") from exc
        with self._lock:
            if self._model is None:
                self._model = WhisperModel(
                    str(self._settings.voice_model_dir),
                    device="cpu",
                    compute_type="int8",
                    cpu_threads=self._settings.voice_cpu_threads,
                    num_workers=self._settings.voice_num_workers,
                    local_files_only=True,
                )
        return self._model

    def prewarm(self) -> None:
        """Load the model ahead of the first recording so users skip the cold start."""

        self._load()

    def transcribe(self, samples: bytes | bytearray) -> str:
        try:
            import numpy as np
        except ImportError as exc:
            raise VoiceModelMissingError("未安装 numpy 语音依赖") from exc
        audio = np.frombuffer(samples, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _ = self._load().transcribe(
            audio,
            language="zh",
            beam_size=self._settings.voice_beam_size,
            vad_filter=self._settings.voice_vad_enabled,
            condition_on_previous_text=False,
        )
        return "".join(segment.text for segment in segments)


@dataclass
class _ActiveRecording:
    id: UUID
    session_id: str
    started_at: datetime
    stream: InputStream
    chunks: list[bytearray] = field(default_factory=list)
    bytes_received: int = 0
    peak_sample: int = 0
    limit_reached: bool = False
    processing: bool = False


class VoiceInputService:
    def __init__(
        self,
        settings: Settings,
        *,
        backend: AudioBackend | None = None,
        transcriber: Transcriber | None = None,
    ) -> None:
        self._settings = settings
        self._backend = backend or SoundDeviceBackend()
        self._transcriber = transcriber or FasterWhisperTranscriber(settings)
        self._lock = threading.Lock()
        self._active: _ActiveRecording | None = None

    def status(self) -> VoiceStatus:
        active = self._active
        dependencies = all(
            importlib.util.find_spec(module) is not None for module in ("sounddevice", "faster_whisper", "numpy")
        )
        available = self._settings.voice_enabled and self._settings.voice_model_dir.is_dir() and dependencies
        message = (
            "正在转写，请稍候"
            if active and active.processing
            else "正在录音，松开后转写"
            if active
            else "按住麦克风按钮开始说话"
            if available
            else "语音输入未启用、依赖缺失或模型不可用"
        )
        return VoiceStatus(
            enabled=self._settings.voice_enabled,
            available=available,
            state="transcribing" if active and active.processing else "recording" if active else "idle",
            model_path=str(self._settings.voice_model_dir),
            model_exists=self._settings.voice_model_dir.is_dir(),
            selected_device=self._settings.voice_input_device,
            max_recording_seconds=self._settings.voice_max_recording_seconds,
            active_recording_id=active.id if active else None,
            level_dbfs=self._level(active) if active else -90.0,
            message=message,
        )

    def devices(self) -> list[VoiceDevice]:
        return self._backend.devices()

    def prewarm(self) -> bool:
        """Best-effort background model load; failures leave voice status untouched."""

        if not (self._settings.voice_enabled and self._settings.voice_model_dir.is_dir()):
            return False
        loader = getattr(self._transcriber, "prewarm", None)
        if loader is None:
            return False
        try:
            loader()
        except Exception:
            return False
        return True

    def start(self, session_id: str) -> VoiceRecording:
        if not self._settings.voice_enabled:
            raise VoiceDeviceUnavailableError("语音输入未启用")
        if not self._settings.voice_model_dir.is_dir():
            raise VoiceModelMissingError(f"Faster-Whisper 模型不存在：{self._settings.voice_model_dir}")
        with self._lock:
            if self._active is not None:
                raise VoiceServiceBusyError("已有录音正在进行")
            recording_id = uuid4()

            def accept(chunk: bytes) -> None:
                self._accept_chunk(recording_id, chunk)

            stream = self._backend.open_stream(self._settings.voice_input_device, accept)
            active = _ActiveRecording(recording_id, session_id, datetime.now(UTC), stream)
            self._active = active
            try:
                stream.start()
            except Exception as exc:
                self._active = None
                try:
                    stream.close()
                finally:
                    raise VoiceDeviceUnavailableError(f"无法启动麦克风：{exc}") from exc
        return self._view(active, "recording")

    async def stop(self, recording_id: UUID, session_id: str) -> VoiceRecording:
        active = self._claim(recording_id, session_id)
        samples = bytearray()
        try:
            self._close_stream(active)
            samples = bytearray().join(active.chunks)
            duration = len(samples) / (SAMPLE_RATE * SAMPLE_WIDTH)
            if duration < self._settings.voice_min_recording_seconds:
                raise RecordingTooShortError("录音时间过短")
            level = self._level(active)
            if level <= self._settings.voice_silence_dbfs:
                raise SilentRecordingError("录音中未检测到有效语音")
            try:
                raw_text = await asyncio.wait_for(
                    asyncio.to_thread(self._transcriber.transcribe, samples),
                    timeout=self._settings.voice_transcription_timeout_seconds,
                )
            except TimeoutError as exc:
                raise VoiceTranscriptionTimeoutError("语音转写超时") from exc
            transcript = normalize_transcript(raw_text)
            if not transcript:
                raise SilentRecordingError("转写结果为空")
            return self._view(active, "completed", transcript=transcript, duration=duration)
        finally:
            if samples:
                samples[:] = b"\x00" * len(samples)
                samples.clear()
            self._release(active)

    def cancel(self, recording_id: UUID, session_id: str) -> VoiceRecording:
        active = self._claim(recording_id, session_id)
        try:
            self._close_stream(active)
            return self._view(active, "cancelled")
        finally:
            self._release(active)

    async def close(self) -> None:
        active = self._active
        if active is not None:
            try:
                self._close_stream(active)
            finally:
                self._release(active)

    def _accept_chunk(self, recording_id: UUID, chunk: bytes) -> None:
        active = self._active
        if active is None or active.id != recording_id or not chunk:
            return
        max_bytes = int(self._settings.voice_max_recording_seconds * SAMPLE_RATE * SAMPLE_WIDTH)
        remaining = max_bytes - active.bytes_received
        if remaining <= 0:
            active.limit_reached = True
            return
        accepted = bytearray(chunk[:remaining])
        active.chunks.append(accepted)
        active.bytes_received += len(accepted)
        samples = memoryview(accepted).cast("h")
        if samples:
            active.peak_sample = max(active.peak_sample, max(abs(sample) for sample in samples))
        if len(accepted) < len(chunk):
            active.limit_reached = True

    def _claim(self, recording_id: UUID, session_id: str) -> _ActiveRecording:
        with self._lock:
            active = self._active
            if active is None or active.id != recording_id:
                raise VoiceDeviceUnavailableError("录音不存在或已结束")
            if active.session_id != session_id:
                raise VoiceDeviceUnavailableError("录音属于另一个会话")
            if active.processing:
                raise VoiceServiceBusyError("录音正在停止或转写")
            active.processing = True
            return active

    def _release(self, active: _ActiveRecording) -> None:
        for chunk in active.chunks:
            if chunk:
                chunk[:] = b"\x00" * len(chunk)
                chunk.clear()
        active.chunks.clear()
        active.bytes_received = 0
        with self._lock:
            if self._active is active:
                self._active = None

    @staticmethod
    def _close_stream(active: _ActiveRecording) -> None:
        try:
            active.stream.stop()
        finally:
            active.stream.close()

    @staticmethod
    def _level(active: _ActiveRecording | None) -> float:
        if active is None or active.peak_sample <= 0:
            return -90.0
        return max(-90.0, 20.0 * math.log10(active.peak_sample / 32768.0))

    def _view(
        self,
        active: _ActiveRecording,
        state: str,
        *,
        transcript: str | None = None,
        duration: float | None = None,
    ) -> VoiceRecording:
        elapsed = duration if duration is not None else (datetime.now(UTC) - active.started_at).total_seconds()
        return VoiceRecording(
            id=active.id,
            state=state,
            started_at=active.started_at,
            duration_seconds=max(0.0, elapsed),
            level_dbfs=self._level(active),
            transcript=transcript,
            limit_reached=active.limit_reached,
        )


_TRADITIONAL_FALLBACK = str.maketrans(
    {
        "臺": "台",
        "後": "后",
        "裡": "里",
        "會": "会",
        "個": "个",
        "項": "项",
        "開": "开",
        "關": "关",
        "處": "处",
        "週": "周",
        "報": "报",
        "議": "议",
    }
)


def normalize_transcript(text: str) -> str:
    try:
        from opencc import OpenCC

        text = OpenCC("t2s").convert(text)
    except ImportError:
        pass
    text = text.translate(_TRADITIONAL_FALLBACK)
    text = text.replace("项目立会", "项目例会")
    return re.sub(r"\s+", " ", text).strip()


__all__ = [
    "AudioBackend",
    "FasterWhisperTranscriber",
    "InputStream",
    "SoundDeviceBackend",
    "Transcriber",
    "VoiceInputService",
    "normalize_transcript",
]
