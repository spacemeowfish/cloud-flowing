from __future__ import annotations

import json
import wave
from pathlib import Path

import pytest

from agent_platform.config import Settings
from agent_platform.config.settings import _application_root
from agent_platform.core.desktop_settings import DesktopSettingsService, PassiveRestartController
from agent_platform.models.admin import DesktopSettingsUpdate


def _wav(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(24000)
        target.writeframes(b"\x00\x00" * 2400)
    return path


def test_agent_app_root_follows_a_moved_portable_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_root = tmp_path / "cloud-flowing-original"
    moved_root = tmp_path / "cloud-flowing-moved"
    original_root.mkdir()
    (original_root / ".env").write_text(
        "AGENT_DATABASE_PATH=data/state.db\n"
        "AGENT_KNOWLEDGE_ROOTS=[\"data/knowledge\",\"demo_docs\"]\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENT_APP_ROOT", str(original_root))
    monkeypatch.chdir(tmp_path)

    before_move = Settings()
    assert before_move.database_path == original_root / "data" / "state.db"
    assert before_move.knowledge_roots == [
        original_root / "data" / "knowledge",
        original_root / "demo_docs",
    ]

    original_root.rename(moved_root)
    monkeypatch.setenv("AGENT_APP_ROOT", str(moved_root))
    after_move = Settings()

    assert _application_root() == moved_root.resolve()
    assert after_move.database_path == moved_root / "data" / "state.db"
    assert after_move.knowledge_roots == [
        moved_root / "data" / "knowledge",
        moved_root / "demo_docs",
    ]


def test_agent_app_root_rejects_a_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    invalid_root = tmp_path / "not-a-directory"
    invalid_root.write_text("invalid", encoding="utf-8")
    monkeypatch.setenv("AGENT_APP_ROOT", str(invalid_root))

    with pytest.raises(ValueError, match="existing directory"):
        _application_root()


@pytest.mark.asyncio
async def test_desktop_settings_store_bundle_paths_as_portable_relative_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle_root = tmp_path / "bundle"
    outside_root = tmp_path / "outside"
    files = bundle_root / "data" / "authorized_files"
    knowledge = bundle_root / "data" / "knowledge"
    zipvoice = bundle_root / "models" / "zipvoice"
    whisper = bundle_root / "models" / "faster-whisper-small"
    for directory in (files, knowledge, zipvoice, whisper, outside_root):
        directory.mkdir(parents=True)
    vocoder = zipvoice / "vocos_24khz.onnx"
    vocoder.write_bytes(b"onnx")
    bundled_voice = _wav(bundle_root / "voices" / "female1.wav")
    external_voice = _wav(outside_root / "external.wav")
    env_path = bundle_root / ".env"
    monkeypatch.setenv("AGENT_APP_ROOT", str(bundle_root))

    settings = Settings(
        _env_file=None,
        database_path="data/agent.db",
        audit_dir="logs/audit",
        authorized_file_roots=[files, outside_root],
        knowledge_roots=[knowledge],
        meeting_output_dir="data/meeting",
    )
    payload = DesktopSettingsUpdate(
        model_provider="mock",
        model_name="qwen2.5:3b",
        ollama_base_url="http://127.0.0.1:11434",
        file_open_enabled=True,
        authorized_file_roots=[files, outside_root],
        knowledge_roots=[knowledge],
        tts_provider="zipvoice",
        zipvoice_model_dir=zipvoice,
        zipvoice_vocoder_path=vocoder,
        zipvoice_num_threads=4,
        zipvoice_speed=1.0,
        zipvoice_default_voice_id="female1",
        zipvoice_voices=[
            {
                "id": "female1",
                "name": "Female 1",
                "reference_wav": bundled_voice,
                "reference_text": "Bundled reference text.",
            },
            {
                "id": "external",
                "name": "External",
                "reference_wav": external_voice,
                "reference_text": "External reference text.",
            },
        ],
        voice_enabled=True,
        voice_input_device="",
        voice_model_dir=whisper,
        voice_cpu_threads=8,
        voice_num_workers=1,
        voice_beam_size=3,
        voice_vad_enabled=True,
        voice_max_recording_seconds=30,
    )
    service = DesktopSettingsService(
        settings,
        PassiveRestartController(),
        env_path=env_path,
    )

    await service.update(payload)

    entries = {
        key: value
        for line in env_path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
        for key, value in [line.split("=", 1)]
    }
    authorized = json.loads(entries["AGENT_AUTHORIZED_FILE_ROOTS"])
    voices = json.loads(entries["ZIPVOICE_VOICES"])
    assert authorized == ["data/authorized_files", str(outside_root.resolve())]
    assert json.loads(entries["AGENT_KNOWLEDGE_ROOTS"]) == ["data/knowledge"]
    assert entries["ZIPVOICE_MODEL_DIR"] == "models/zipvoice"
    assert entries["ZIPVOICE_VOCODER_PATH"] == "models/zipvoice/vocos_24khz.onnx"
    assert entries["VOICE_MODEL_DIR"] == "models/faster-whisper-small"
    assert voices[0]["reference_audio_path"] == "voices/female1.wav"
    assert voices[1]["reference_audio_path"] == str(external_voice.resolve())

    reloaded = Settings(_env_file=env_path)
    assert reloaded.authorized_file_roots == [files, outside_root]
    assert reloaded.zipvoice_model_dir == zipvoice
    assert reloaded.zipvoice_vocoder_path == vocoder
    assert reloaded.voice_model_dir == whisper
    assert reloaded.zipvoice_voices[0].reference_audio_path == bundled_voice
    assert reloaded.zipvoice_voices[1].reference_audio_path == external_voice
