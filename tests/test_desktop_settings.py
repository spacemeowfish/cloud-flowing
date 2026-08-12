from __future__ import annotations

import os
import wave
from pathlib import Path

import httpx
import pytest

from agent_platform.api.server import create_app
from agent_platform.config import Settings
from agent_platform.core.desktop_settings import DesktopSettingsService, PassiveRestartController
from agent_platform.core.desktop_supervisor import DesktopRestartController
from agent_platform.models.admin import DesktopSettingsUpdate


def _wav(path: Path) -> Path:
    with wave.open(str(path), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(24000)
        target.writeframes(b"\x00\x00" * 2400)
    return path


def _settings(tmp_path: Path) -> Settings:
    files = tmp_path / "files"
    knowledge = tmp_path / "knowledge"
    files.mkdir()
    knowledge.mkdir()
    return Settings(
        _env_file=None,
        model_provider="mock",
        database_path=tmp_path / "agent.db",
        audit_dir=tmp_path / "audit",
        authorized_file_roots=[files],
        knowledge_roots=[knowledge],
        meeting_output_dir=tmp_path / "meeting",
    )


def _payload(tmp_path: Path, settings: Settings) -> DesktopSettingsUpdate:
    zip_dir = tmp_path / "zipvoice"
    whisper = tmp_path / "whisper"
    zip_dir.mkdir(exist_ok=True)
    whisper.mkdir(exist_ok=True)
    vocoder = zip_dir / "vocoder.onnx"
    vocoder.write_bytes(b"onnx")
    reference = _wav(tmp_path / "voice.wav")
    return DesktopSettingsUpdate(
        model_provider="mock",
        model_name="qwen2.5:3b",
        ollama_base_url="http://127.0.0.1:11434",
        file_open_enabled=True,
        authorized_file_roots=settings.authorized_file_roots,
        knowledge_roots=settings.knowledge_roots,
        tts_provider="zipvoice",
        zipvoice_model_dir=zip_dir,
        zipvoice_vocoder_path=vocoder,
        zipvoice_num_threads=4,
        zipvoice_speed=1.0,
        zipvoice_default_voice_id="female1",
        zipvoice_voices=[
            {
                "id": "female1",
                "name": "女声 1",
                "reference_wav": reference,
                "reference_text": "参考文本",
            }
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


@pytest.mark.asyncio
async def test_env_update_preserves_secrets_and_keeps_five_backups(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("MODEL_API_KEY=keep-me\nUNKNOWN_SETTING=keep-too\nMODEL_PROVIDER=mock\n", encoding="utf-8")
    settings = _settings(tmp_path)
    controller = PassiveRestartController()
    service = DesktopSettingsService(settings, controller, env_path=env_path)
    payload = _payload(tmp_path, settings)

    for index in range(7):
        payload.file_open_enabled = bool(index % 2)
        await service.update(payload)

    content = env_path.read_text(encoding="utf-8")
    assert "MODEL_API_KEY=keep-me" in content
    assert "UNKNOWN_SETTING=keep-too" in content
    assert "AGENT_FILE_OPEN_ENABLED=false" in content
    assert len(list((tmp_path / ".env.backups").glob("*.env"))) == 5
    view = await service.view(include_models=False)
    assert not hasattr(view, "model_api_key")
    assert controller.status().state == "manual_restart_required"


@pytest.mark.asyncio
async def test_process_environment_locks_field(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(tmp_path)
    env_path = tmp_path / ".env"
    monkeypatch.setenv("MODEL_PROVIDER", "mock")
    service = DesktopSettingsService(settings, PassiveRestartController(), env_path=env_path)
    payload = _payload(tmp_path, settings)

    await service.update(payload)

    assert "model_provider" in service.locked_fields
    assert "MODEL_PROVIDER=" not in env_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_admin_api_never_exposes_secret_and_reindexes(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    (settings.knowledge_roots[0] / "policy.txt").write_text("产品保修期为两年。", encoding="utf-8")
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/admin/settings")
            assert response.status_code == 200
            assert "api_key" not in response.text.casefold()
            report = await client.post("/admin/knowledge/reindex")
            assert report.status_code == 200
            assert report.json()["scanned"] == 1
            assert report.json()["imported"] == 1
            status = await client.get("/admin/restart-status")
            assert status.json()["supervised"] is False


def test_supervised_restart_controller_requests_exit_and_tracks_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_path = tmp_path / ".env"
    backup = tmp_path / "backup.env"
    env_path.write_text("MODEL_PROVIDER=ollama\n", encoding="utf-8")
    backup.write_text("MODEL_PROVIDER=mock\n", encoding="utf-8")
    monkeypatch.setattr("agent_platform.core.desktop_supervisor.restore_env_backup", lambda path: path == backup)

    class _Server:
        should_exit = False

    controller = DesktopRestartController()
    server = _Server()
    controller.bind(server)
    controller.request_restart(backup)
    controller._stop_bound_server(server)

    assert server.should_exit is True
    assert controller.status().state == "restarting"
    assert controller.rollback("startup failed") is True
    assert controller.status().rollback_performed is True
