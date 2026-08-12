import asyncio
import io
import wave

import httpx
import pytest

from agent_platform.api.server import create_app
from agent_platform.adapters.zipvoice_tts import ZipVoiceReference, ZipVoiceSpeechSynthesizer
from agent_platform.config import Settings
from agent_platform.core.errors import SpeechUnavailableError
from agent_platform.core.interfaces import SpeechAudio, SpeechSynthesizer
from agent_platform.core.speech_output import SpeechOutputService
from agent_platform.models import TaskState


class _FakeSpeechSynthesizer(SpeechSynthesizer):
    def __init__(self) -> None:
        self.requests: list[tuple[str, str | None]] = []

    async def synthesize(self, text: str, voice_id: str | None = None) -> SpeechAudio:
        self.requests.append((text, voice_id))
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(16000)
            output.writeframes(b"\x00\x00" * 1600)
        return SpeechAudio(buffer.getvalue(), 16000, 0.1, voice_id or "female", "新闻女声")

    def status(self):
        return {
            "enabled": True,
            "provider": "fake",
            "configured": True,
            "dependency_available": True,
            "ready": True,
            "model_loaded": True,
            "missing_resource_count": 0,
            "default_voice_id": "female",
            "voices": [
                {"id": "female", "label": "新闻女声", "available": True},
                {"id": "male", "label": "男声", "available": True},
            ],
        }


async def _wait_completed(client: httpx.AsyncClient, task_id: str) -> dict[str, object]:
    for _ in range(100):
        task = (await client.get(f"/tasks/{task_id}")).json()
        if task["state"] == TaskState.COMPLETED.value:
            return task
        await asyncio.sleep(0.02)
    raise AssertionError("task did not complete")


def _settings(tmp_path) -> Settings:
    allowed = tmp_path / "allowed"
    knowledge = tmp_path / "knowledge"
    allowed.mkdir()
    knowledge.mkdir()
    return Settings(
        _env_file=None,
        model_provider="mock",
        database_path=tmp_path / "agent.db",
        audit_dir=tmp_path / "audit",
        authorized_file_roots=[allowed],
        knowledge_roots=[knowledge],
        meeting_output_dir=tmp_path / "meeting",
        tts_provider="disabled",
        tts_output_dir=tmp_path / "tts",
        audit_flush_size=1,
    )


@pytest.mark.asyncio
async def test_completed_task_speech_can_be_regenerated_and_downloaded(tmp_path):
    settings = _settings(tmp_path)
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        fake = _FakeSpeechSynthesizer()
        app.state.container.speech = SpeechOutputService(
            tasks=app.state.container.tasks,
            synthesizer=fake,
            output_dir=settings.tts_output_dir,
            max_chars=2000,
            keep_versions=1,
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            task = (await client.post("/tasks", json={"text": "1+1=?"})).json()
            completed = await _wait_completed(client, task["id"])
            expected_text = completed["result"]["output"]["answer"]

            first = await client.post(f"/tasks/{task['id']}/speech", json={"voice_id": "female"})
            assert first.status_code == 201
            first_artifact = first.json()
            audio = await client.get(first_artifact["audio_url"])
            assert audio.status_code == 200
            assert audio.headers["content-type"].startswith("audio/wav")
            assert audio.content.startswith(b"RIFF")
            assert first_artifact["voice_id"] == "female"
            assert first_artifact["voice_label"] == "新闻女声"

            second = await client.post(f"/tasks/{task['id']}/speech", json={"voice_id": "male"})
            assert second.status_code == 201
            assert second.json()["version_id"] != first_artifact["version_id"]
            assert fake.requests == [(expected_text, "female"), (expected_text, "male")]
            expired = await client.get(first_artifact["audio_url"])
            assert expired.status_code == 400


@pytest.mark.asyncio
async def test_speech_rejects_unfinished_or_cross_session_tasks(tmp_path):
    settings = _settings(tmp_path)
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        app.state.container.speech = SpeechOutputService(
            tasks=app.state.container.tasks,
            synthesizer=_FakeSpeechSynthesizer(),
            output_dir=settings.tts_output_dir,
            max_chars=2000,
            keep_versions=3,
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            task = (await client.post(
                "/tasks",
                json={"text": "1+1=?"},
                headers={"X-Session-Id": "owner"},
            )).json()
            pending = await client.post(
                f"/tasks/{task['id']}/speech",
                json={},
                headers={"X-Session-Id": "owner"},
            )
            assert pending.status_code == 400
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://test",
                headers={"X-Session-Id": "owner"},
            ) as owner_client:
                await _wait_completed(owner_client, task["id"])
            forbidden = await client.post(
                f"/tasks/{task['id']}/speech",
                json={},
                headers={"X-Session-Id": "other"},
            )
            assert forbidden.status_code == 403


@pytest.mark.asyncio
async def test_tts_capability_does_not_change_agent_tool_set(tmp_path):
    app = create_app(_settings(tmp_path))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            capabilities = (await client.get("/meta/capabilities")).json()
            assert capabilities["tts"]["provider"] == "disabled"
            assert capabilities["tts"]["enabled"] is False
            assert len(capabilities["tools"]) == 8


@pytest.mark.asyncio
async def test_speech_capabilities_publish_selectable_voices(tmp_path):
    settings = _settings(tmp_path)
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        app.state.container.speech = SpeechOutputService(
            tasks=app.state.container.tasks,
            synthesizer=_FakeSpeechSynthesizer(),
            output_dir=settings.tts_output_dir,
            max_chars=2000,
            keep_versions=3,
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            tts = (await client.get("/meta/capabilities")).json()["tts"]
            assert tts["default_voice_id"] == "female"
            assert [voice["id"] for voice in tts["voices"]] == ["female", "male"]


@pytest.mark.asyncio
async def test_zipvoice_rejects_unknown_or_unavailable_voice_before_loading_model(tmp_path):
    missing = tmp_path / "missing.wav"
    synthesizer = ZipVoiceSpeechSynthesizer(
        model_dir=tmp_path,
        vocoder_path=tmp_path / "vocoder.onnx",
        reference_audio_path=missing,
        reference_text="legacy",
        voices=(ZipVoiceReference("missing", "缺失音色", missing, "参考文本"),),
        default_voice_id="missing",
        num_threads=1,
        speed=1.0,
        num_steps=4,
    )
    with pytest.raises(SpeechUnavailableError, match="未知 ZipVoice 音色"):
        await synthesizer.synthesize("测试", "unknown")
    with pytest.raises(SpeechUnavailableError, match="ZipVoice 音色不可用"):
        await synthesizer.synthesize("测试", "missing")
    status = synthesizer.status()
    assert status["voices"] == [{"id": "missing", "label": "缺失音色", "available": False}]
    assert status["default_voice_id"] == ""


def test_zipvoice_loads_pcm24_reference_audio(tmp_path):
    np = pytest.importorskip("numpy")
    reference_audio = tmp_path / "female1.wav"
    pcm24_values = (-8388608, -1, 0, 1, 8388607)
    frames = b"".join((value & 0xFFFFFF).to_bytes(3, "little") for value in pcm24_values)
    with wave.open(str(reference_audio), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(3)
        output.setframerate(48000)
        output.writeframes(frames)

    synthesizer = ZipVoiceSpeechSynthesizer(
        model_dir=tmp_path,
        vocoder_path=tmp_path / "vocoder.onnx",
        reference_audio_path=reference_audio,
        reference_text="参考文本",
        voices=(ZipVoiceReference("female1", "female1", reference_audio, "参考文本"),),
        default_voice_id="female1",
        num_threads=1,
        speed=1.0,
        num_steps=4,
    )

    samples, sample_rate = synthesizer._load_prompt(synthesizer._voices["female1"], np)

    assert sample_rate == 48000
    assert samples.dtype == np.float32
    assert samples.tolist() == pytest.approx([-1.0, -1 / 8388608, 0.0, 1 / 8388608, 8388607 / 8388608])
