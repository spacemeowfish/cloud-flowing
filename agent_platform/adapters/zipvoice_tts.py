"""ZipVoice speech synthesis through the optional sherpa-onnx runtime."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import io
import os
import shutil
import tempfile
import threading
import wave
from dataclasses import dataclass
from pathlib import Path

from pydantic import JsonValue

from agent_platform.core.errors import SpeechSynthesisError, SpeechUnavailableError
from agent_platform.core.interfaces import SpeechAudio, SpeechSynthesizer


@dataclass(frozen=True)
class ZipVoiceReference:
    id: str
    label: str
    audio_path: Path
    text: str


class ZipVoiceSpeechSynthesizer(SpeechSynthesizer):
    """Lazily load one external ZipVoice model and serialize CPU inference."""

    def __init__(
        self,
        *,
        model_dir: Path,
        vocoder_path: Path,
        reference_audio_path: Path,
        reference_text: str,
        voices: tuple[ZipVoiceReference, ...] = (),
        default_voice_id: str = "default",
        num_threads: int,
        speed: float,
        num_steps: int,
    ) -> None:
        self._model_dir = model_dir.resolve()
        self._vocoder_path = vocoder_path.resolve()
        legacy = ZipVoiceReference(
            id="default",
            label="默认音色",
            audio_path=reference_audio_path.resolve(),
            text=reference_text.strip(),
        )
        selected_voices = voices or (legacy,)
        self._voices = {
            voice.id: ZipVoiceReference(
                id=voice.id,
                label=voice.label,
                audio_path=voice.audio_path.resolve(),
                text=voice.text.strip(),
            )
            for voice in selected_voices
        }
        available_voice_ids = [
            voice.id for voice in self._voices.values() if voice.audio_path.is_file() and voice.text
        ]
        self._default_voice_id = (
            default_voice_id if default_voice_id in available_voice_ids else next(iter(available_voice_ids), "")
        )
        self._num_threads = num_threads
        self._speed = speed
        self._num_steps = num_steps
        self._engine: object | None = None
        self._prompts: dict[str, tuple[object, int]] = {}
        self._runtime_lock = threading.Lock()
        self._closed = False

    async def synthesize(self, text: str, voice_id: str | None = None) -> SpeechAudio:
        if self._closed:
            raise SpeechUnavailableError("ZipVoice 已关闭，请重启 Agent 服务")
        selected_voice_id = voice_id or self._default_voice_id
        if selected_voice_id not in self._voices:
            raise SpeechUnavailableError(f"未知 ZipVoice 音色：{selected_voice_id}")
        selected_voice = self._voices[selected_voice_id]
        if not selected_voice.audio_path.is_file() or not selected_voice.text:
            raise SpeechUnavailableError(f"ZipVoice 音色不可用：{selected_voice_id}")
        return await asyncio.to_thread(self._synthesize_blocking, text, selected_voice_id)

    def status(self) -> dict[str, JsonValue]:
        missing = [str(path) for path in self._required_paths() if not path.is_file() and not path.is_dir()]
        dependency_available = importlib.util.find_spec("sherpa_onnx") is not None
        voices = [
            {
                "id": voice.id,
                "label": voice.label,
                "available": voice.audio_path.is_file() and bool(voice.text),
            }
            for voice in self._voices.values()
        ]
        configured = not missing and any(voice["available"] for voice in voices)
        return {
            "enabled": True,
            "provider": "zipvoice",
            "configured": configured,
            "dependency_available": dependency_available,
            "ready": configured and dependency_available,
            "model_loaded": self._engine is not None,
            "missing_resource_count": len(missing),
            "default_voice_id": self._default_voice_id,
            "voices": voices,
        }

    async def close(self) -> None:
        self._closed = True
        with self._runtime_lock:
            self._engine = None
            self._prompts.clear()

    def _required_paths(self) -> tuple[Path, ...]:
        return (
            self._model_dir / "encoder.int8.onnx",
            self._model_dir / "decoder.int8.onnx",
            self._model_dir / "tokens.txt",
            self._model_dir / "lexicon.txt",
            self._model_dir / "espeak-ng-data",
            self._vocoder_path,
        )

    def _espeak_data_dir(self) -> Path:
        """Return an ASCII-only espeak-ng-data path for the sherpa-onnx engine.

        sherpa-onnx bundles espeak-ng (C code) which cannot read espeak-ng-data
        from a path containing non-ASCII characters. On Windows with a Chinese
        path this surfaces as "Illegal byte sequence" while loading phontab.
        Copy the data to a temp ASCII directory only when the model path is not
        ASCII, and cache the copy by a hash of the source path.
        """
        source = self._model_dir / "espeak-ng-data"
        if str(source).isascii():
            return source
        target = Path(tempfile.gettempdir()) / (
            "espeak-ng-data-" + hashlib.sha256(str(source).encode("utf-8")).hexdigest()[:12]
        )
        if not target.exists():
            shutil.copytree(source, target)
        return target

    def _synthesize_blocking(self, text: str, voice_id: str) -> SpeechAudio:
        with self._runtime_lock:
            engine, np = self._load_engine()
            voice = self._voices[voice_id]
            prompt_samples, prompt_sample_rate = self._load_prompt(voice, np)
            try:
                audio = engine.generate(
                    text,
                    voice.text,
                    prompt_samples,
                    prompt_sample_rate,
                    self._speed,
                    self._num_steps,
                )
            except Exception as exc:
                raise SpeechSynthesisError(f"ZipVoice 生成失败：{type(exc).__name__}: {exc}") from exc

            samples = np.clip(
                np.asarray(audio.samples, dtype=np.float32) * 32767,
                -32768,
                32767,
            ).astype(np.int16)
            if not samples.size:
                raise SpeechSynthesisError("ZipVoice 返回了空音频")
            sample_rate = int(audio.sample_rate)
            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(sample_rate)
                output.writeframes(samples.tobytes())
            return SpeechAudio(
                wav_bytes=buffer.getvalue(),
                sample_rate=sample_rate,
                duration_seconds=float(samples.size / sample_rate),
                voice_id=voice.id,
                voice_label=voice.label,
            )

    def _load_engine(self):
        if self._engine is not None:
            import numpy as np

            return self._engine, np

        missing = [str(path) for path in self._required_paths() if not path.is_file() and not path.is_dir()]
        if missing:
            raise SpeechUnavailableError("ZipVoice 资源不完整：" + "；".join(missing))
        if not self._voices:
            raise SpeechUnavailableError("ZIPVOICE_VOICES 未配置")
        try:
            import numpy as np
            import sherpa_onnx
        except ImportError as exc:
            raise SpeechUnavailableError("未安装 TTS 依赖，请运行 python -m pip install -e \".[tts]\"") from exc

        espeak_data = self._espeak_data_dir()
        os.environ["ESPEAK_DATA_PATH"] = str(espeak_data)
        zipvoice = sherpa_onnx.OfflineTtsZipvoiceModelConfig(
            tokens=str(self._model_dir / "tokens.txt"),
            encoder=str(self._model_dir / "encoder.int8.onnx"),
            decoder=str(self._model_dir / "decoder.int8.onnx"),
            vocoder=str(self._vocoder_path),
            data_dir=str(espeak_data),
            lexicon=str(self._model_dir / "lexicon.txt"),
        )
        model = sherpa_onnx.OfflineTtsModelConfig(
            zipvoice=zipvoice,
            num_threads=self._num_threads,
            debug=False,
            provider="cpu",
        )
        config = sherpa_onnx.OfflineTtsConfig(
            model=model,
            max_num_sentences=1,
            silence_scale=0.2,
        )
        if not config.validate():
            raise SpeechUnavailableError("ZipVoice 配置校验失败")
        try:
            engine = sherpa_onnx.OfflineTts(config)
        except Exception as exc:
            raise SpeechUnavailableError(f"ZipVoice 模型加载失败：{type(exc).__name__}: {exc}") from exc
        self._engine = engine
        return engine, np

    def _load_prompt(self, voice: ZipVoiceReference, np):
        cached = self._prompts.get(voice.id)
        if cached is not None:
            return cached
        with wave.open(str(voice.audio_path), "rb") as source:
            channels = source.getnchannels()
            sample_width = source.getsampwidth()
            sample_rate = source.getframerate()
            frames = source.readframes(source.getnframes())
        if channels != 1 or sample_width not in {2, 3}:
            raise SpeechUnavailableError("ZipVoice 参考音频必须是单声道 PCM16 或 PCM24 WAV")
        if sample_width == 2:
            samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
        else:
            packed = np.frombuffer(frames, dtype=np.uint8).reshape(-1, 3)
            samples = (
                packed[:, 0].astype(np.int32)
                | (packed[:, 1].astype(np.int32) << 8)
                | (packed[:, 2].astype(np.int32) << 16)
            )
            samples = np.where(samples & 0x800000, samples - 0x1000000, samples)
            samples = samples.astype(np.float32) / 8388608.0
        prompt = (samples, int(sample_rate))
        self._prompts[voice.id] = prompt
        return prompt


__all__ = ["ZipVoiceReference", "ZipVoiceSpeechSynthesizer"]
