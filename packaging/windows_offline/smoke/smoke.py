"""Run real-model, Faster-Whisper, and ZipVoice bundle smoke checks."""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import wave
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx


GENERAL_CHAT_PROMPT = "请用一句话说明局域网交换机的作用？"
ASR_FIXTURE_TEXT = "局域网交换机用于连接多台设备。"
VOICE_IDS = ("news-female1", "male1", "female1", "female2")
TERMINAL_STATES = {"completed", "failed", "cancelled"}
_DRIVE_PATH = re.compile(r"(?i)(?:[a-z]:[\\/][^\r\n\"']*)")
_UNC_PATH = re.compile(r"(?:\\\\[^\\\s]+\\[^\r\n\"']*)")


class SmokeFailure(RuntimeError):
    """A failed acceptance assertion with a concise operator-facing message."""


def _round_seconds(value: float) -> float:
    return round(value, 3)


def _redact_local_paths(value: object, bundle_root: Path) -> str:
    text = str(value)
    roots = {
        str(bundle_root.resolve()),
        str(bundle_root.resolve()).replace("\\", "/"),
    }
    for root in sorted(roots, key=len, reverse=True):
        text = text.replace(root, "<bundle>")
    text = _DRIVE_PATH.sub("<local-path>", text)
    return _UNC_PATH.sub("<local-path>", text)


def _sanitize_for_report(value: Any, bundle_root: Path) -> Any:
    if isinstance(value, str):
        return _redact_local_paths(value, bundle_root)
    if isinstance(value, dict):
        return {str(key): _sanitize_for_report(item, bundle_root) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_for_report(item, bundle_root) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_for_report(item, bundle_root) for item in value]
    return value


def _check(
    name: str,
    action: Callable[[], dict[str, Any]],
    bundle_root: Path,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    started = time.perf_counter()
    try:
        details = action()
        return (
            {
                "name": name,
                "passed": True,
                "elapsed_seconds": _round_seconds(time.perf_counter() - started),
                "details": details,
                "error": None,
            },
            details,
        )
    except Exception as exc:  # Continue later checks and preserve all evidence.
        return (
            {
                "name": name,
                "passed": False,
                "elapsed_seconds": _round_seconds(time.perf_counter() - started),
                "details": {},
                "error": _redact_local_paths(f"{type(exc).__name__}: {exc}", bundle_root),
            },
            None,
        )


def _llama_root(url: str) -> str:
    normalized = url.rstrip("/")
    if normalized.endswith("/v1"):
        normalized = normalized[:-3]
    return normalized.rstrip("/")


def _response_excerpt(response: httpx.Response) -> str:
    try:
        payload = response.json()
        return json.dumps(payload, ensure_ascii=False)[:1000]
    except ValueError:
        return response.text[:1000]


def _require_http_ok(response: httpx.Response, label: str) -> None:
    if not response.is_success:
        raise SmokeFailure(f"{label} returned HTTP {response.status_code}: {_response_excerpt(response)}")


def _extract_chat_answer(payload: dict[str, Any]) -> str:
    try:
        answer = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise SmokeFailure("llama.cpp response did not contain choices[0].message.content") from exc
    if not isinstance(answer, str) or not answer.strip():
        raise SmokeFailure("llama.cpp returned an empty answer")
    return answer.strip()


def _extract_agent_answer(task: dict[str, Any]) -> str:
    result = task.get("result")
    if not isinstance(result, dict):
        raise SmokeFailure("completed Agent task has no result object")
    if result.get("tool_name") != "general_chat":
        raise SmokeFailure(f"Agent selected {result.get('tool_name')!r}, expected 'general_chat'")
    output = result.get("output")
    if isinstance(output, dict):
        for key in ("answer", "text", "message"):
            value = output.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    summary = result.get("output_summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    raise SmokeFailure("general_chat completed without a non-empty model answer")


def _wait_task(client: httpx.Client, task_id: str, timeout_seconds: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        response = client.get(f"/tasks/{task_id}")
        _require_http_ok(response, "Agent task poll")
        task = response.json()
        state = str(task.get("state", ""))
        if state in TERMINAL_STATES:
            return task
        if state == "awaiting_confirmation":
            raise SmokeFailure("general_chat unexpectedly entered human confirmation")
        time.sleep(0.25)
    raise SmokeFailure(f"Agent task did not reach a terminal state within {timeout_seconds:g}s")


def _submit_agent_task(
    agent_url: str,
    session_id: str,
    timeout_seconds: float,
) -> tuple[dict[str, Any], str]:
    headers = {"X-Session-Id": session_id}
    with httpx.Client(
        base_url=agent_url.rstrip("/"),
        headers=headers,
        timeout=timeout_seconds,
        trust_env=False,
    ) as client:
        response = client.post("/tasks", json={"text": GENERAL_CHAT_PROMPT})
        _require_http_ok(response, "Agent task creation")
        created = response.json()
        task_id = str(created.get("id", ""))
        if not task_id:
            raise SmokeFailure("Agent task creation returned no id")
        if created.get("session_id") != session_id:
            raise SmokeFailure("Agent did not preserve the X-Session-Id owner")
        task = _wait_task(client, task_id, timeout_seconds)
    if task.get("state") != "completed":
        raise SmokeFailure(f"Agent task ended in {task.get('state')!r}: {task.get('error')}")
    answer = _extract_agent_answer(task)
    if answer == GENERAL_CHAT_PROMPT or len(answer) < 4:
        raise SmokeFailure("general_chat did not return a substantive model answer")
    return task, answer


def run_model_phase(
    *,
    bundle_root: Path,
    llama_url: str,
    agent_url: str,
    model_id: str,
    timeout_seconds: float,
) -> tuple[list[dict[str, Any]], dict[str, str] | None]:
    checks: list[dict[str, Any]] = []
    context: dict[str, str] | None = None
    llama_base = _llama_root(llama_url)

    def llama_health() -> dict[str, Any]:
        with httpx.Client(timeout=timeout_seconds, trust_env=False) as client:
            response = client.get(f"{llama_base}/health")
        _require_http_ok(response, "llama.cpp health")
        return {"http_status": response.status_code, "body": _response_excerpt(response)}

    check, _ = _check("llama_health", llama_health, bundle_root)
    checks.append(check)

    def direct_chat() -> dict[str, Any]:
        with httpx.Client(timeout=timeout_seconds, trust_env=False) as client:
            response = client.post(
                f"{llama_base}/v1/chat/completions",
                json={
                    "model": model_id,
                    "messages": [{"role": "user", "content": GENERAL_CHAT_PROMPT}],
                    "temperature": 0.2,
                    "max_tokens": 128,
                    "stream": False,
                },
            )
        _require_http_ok(response, "llama.cpp chat completion")
        answer = _extract_chat_answer(response.json())
        return {"model_id": model_id, "prompt": GENERAL_CHAT_PROMPT, "answer": answer}

    check, _ = _check("llama_direct_chat", direct_chat, bundle_root)
    checks.append(check)

    session_id = f"offline-smoke-{uuid4()}"

    def agent_capabilities() -> dict[str, Any]:
        with httpx.Client(timeout=timeout_seconds, trust_env=False) as client:
            response = client.get(f"{agent_url.rstrip('/')}/meta/capabilities")
        _require_http_ok(response, "Agent capabilities")
        platform = response.json().get("platform", {})
        if platform.get("model_provider") != "llamacpp":
            raise SmokeFailure(
                f"Agent provider is {platform.get('model_provider')!r}, expected 'llamacpp'"
            )
        active_model = str(platform.get("model_name", ""))
        if not active_model:
            raise SmokeFailure("Agent capabilities returned no active model name")
        if active_model != model_id:
            raise SmokeFailure(
                f"Agent active model is {active_model!r}, expected command model {model_id!r}"
            )
        return {"provider": "llamacpp", "active_model": active_model}

    check, _ = _check("agent_llamacpp_capabilities", agent_capabilities, bundle_root)
    checks.append(check)

    def agent_general_chat() -> dict[str, Any]:
        nonlocal context
        task, answer = _submit_agent_task(agent_url, session_id, timeout_seconds)
        context = {"task_id": str(task["id"]), "session_id": session_id}
        return {
            "model_id": model_id,
            "task_id": str(task["id"]),
            "tool_name": task["result"]["tool_name"],
            "prompt": GENERAL_CHAT_PROMPT,
            "answer": answer,
        }

    check, _ = _check("agent_general_chat_real_model", agent_general_chat, bundle_root)
    checks.append(check)
    return checks, context


def _validate_wav_bytes(audio: bytes) -> dict[str, Any]:
    if not audio.startswith(b"RIFF"):
        raise SmokeFailure("audio does not start with a RIFF WAV header")
    try:
        with wave.open(io.BytesIO(audio), "rb") as source:
            channels = source.getnchannels()
            sample_width = source.getsampwidth()
            sample_rate = source.getframerate()
            frame_count = source.getnframes()
    except (EOFError, wave.Error) as exc:
        raise SmokeFailure(f"invalid WAV data: {exc}") from exc
    if channels != 1 or sample_width != 2 or sample_rate < 8000 or frame_count <= 0:
        raise SmokeFailure(
            "WAV must be non-empty mono PCM16 with a sample rate of at least 8000 Hz"
        )
    return {
        "channels": channels,
        "sample_width_bytes": sample_width,
        "sample_rate": sample_rate,
        "frame_count": frame_count,
        "wav_bytes": len(audio),
        "duration_seconds": round(frame_count / sample_rate, 3),
    }


def _artifact_relative_path(path: Path, bundle_root: Path) -> str:
    try:
        return path.resolve().relative_to(bundle_root.resolve()).as_posix()
    except ValueError as exc:
        raise SmokeFailure("TTS artifacts directory must be inside the bundle root") from exc


def run_tts_phase(
    *,
    bundle_root: Path,
    agent_url: str,
    timeout_seconds: float,
    artifacts_dir: Path,
    task_context: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    artifacts_dir = artifacts_dir.resolve()
    _artifact_relative_path(artifacts_dir, bundle_root)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    context = task_context

    def capabilities() -> dict[str, Any]:
        with httpx.Client(timeout=timeout_seconds, trust_env=False) as client:
            response = client.get(f"{agent_url.rstrip('/')}/meta/capabilities")
        _require_http_ok(response, "Agent capabilities")
        tts = response.json().get("tts", {})
        configured_ids = {
            str(voice.get("id"))
            for voice in tts.get("voices", [])
            if isinstance(voice, dict) and voice.get("available")
        }
        missing = sorted(set(VOICE_IDS) - configured_ids)
        if tts.get("provider") != "zipvoice" or not tts.get("ready") or missing:
            raise SmokeFailure(
                f"ZipVoice is not ready with all four required voices; missing={missing}"
            )
        return {"provider": "zipvoice", "ready": True, "voice_ids": list(VOICE_IDS)}

    check, _ = _check("tts_capabilities", capabilities, bundle_root)
    checks.append(check)

    if context is None:
        session_id = f"offline-smoke-tts-{uuid4()}"

        def source_task() -> dict[str, Any]:
            nonlocal context
            task, answer = _submit_agent_task(agent_url, session_id, timeout_seconds)
            context = {"task_id": str(task["id"]), "session_id": session_id}
            return {
                "task_id": str(task["id"]),
                "state": task["state"],
                "tool_name": task["result"]["tool_name"],
                "answer": answer,
            }

        check, _ = _check("tts_completed_source_task", source_task, bundle_root)
        checks.append(check)

    if context is None:
        for voice_id in VOICE_IDS:
            checks.append(
                {
                    "name": f"tts_voice_{voice_id}",
                    "passed": False,
                    "elapsed_seconds": 0.0,
                    "details": {},
                    "error": "SmokeFailure: no completed same-session Agent task is available",
                }
            )
        return checks

    for voice_id in VOICE_IDS:

        def synthesize(selected_voice: str = voice_id) -> dict[str, Any]:
            headers = {"X-Session-Id": context["session_id"]}
            with httpx.Client(
                base_url=agent_url.rstrip("/"),
                headers=headers,
                timeout=timeout_seconds,
                trust_env=False,
            ) as client:
                response = client.post(
                    f"/tasks/{context['task_id']}/speech", json={"voice_id": selected_voice}
                )
                _require_http_ok(response, f"ZipVoice {selected_voice} synthesis")
                artifact = response.json()
                if artifact.get("voice_id") != selected_voice:
                    raise SmokeFailure(
                        f"ZipVoice returned voice {artifact.get('voice_id')!r}, expected {selected_voice!r}"
                    )
                audio_response = client.get(str(artifact["audio_url"]))
                _require_http_ok(audio_response, f"ZipVoice {selected_voice} audio download")
                wav_details = _validate_wav_bytes(audio_response.content)
            target = artifacts_dir / f"tts-{selected_voice}.wav"
            target.write_bytes(audio_response.content)
            return {
                "voice_id": selected_voice,
                "voice_label": artifact.get("voice_label"),
                "artifact": _artifact_relative_path(target, bundle_root),
                **wav_details,
            }

        check, _ = _check(f"tts_voice_{voice_id}", synthesize, bundle_root)
        checks.append(check)
    return checks


def _powershell_executable() -> str:
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    candidate = Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return str(candidate) if candidate.is_file() else "powershell.exe"


def run_asr_phase(
    *,
    bundle_root: Path,
    timeout_seconds: float,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    temp_parent = bundle_root / "logs" / "smoke" / "tmp"
    temp_parent.mkdir(parents=True, exist_ok=True)
    fixture_path: Path | None = None
    pcm: bytearray | None = None
    state: dict[str, Any] = {}

    def generate_fixture() -> dict[str, Any]:
        nonlocal fixture_path, pcm
        if os.name != "nt":
            raise SmokeFailure("SAPI smoke generation requires Windows")
        handle, raw_path = tempfile.mkstemp(prefix="sapi-", suffix=".wav", dir=temp_parent)
        os.close(handle)
        fixture_path = Path(raw_path)
        fixture_path.unlink(missing_ok=True)
        script = Path(__file__).with_name("new-sapi-fixture.ps1")
        completed = subprocess.run(
            [
                _powershell_executable(),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-OutputPath",
                str(fixture_path),
                "-Text",
                ASR_FIXTURE_TEXT,
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout_seconds,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode != 0:
            raise SmokeFailure(completed.stderr.strip() or completed.stdout.strip() or "SAPI failed")
        if not fixture_path.is_file():
            raise SmokeFailure("SAPI reported success but produced no WAV")
        with wave.open(str(fixture_path), "rb") as source:
            if (
                source.getnchannels() != 1
                or source.getsampwidth() != 2
                or source.getframerate() != 16000
            ):
                raise SmokeFailure("SAPI fixture is not 16 kHz mono PCM16")
            pcm = bytearray(source.readframes(source.getnframes()))
        metadata = json.loads(completed.stdout.strip().splitlines()[-1])
        if not pcm:
            raise SmokeFailure("SAPI fixture contains no PCM frames")
        state["voice"] = str(metadata.get("voice", ""))
        return {
            "voice": state["voice"],
            "text": ASR_FIXTURE_TEXT,
            "format": "pcm_s16le_16000_mono",
            "pcm_bytes": len(pcm),
        }

    check, _ = _check("asr_sapi_fixture", generate_fixture, bundle_root)
    checks.append(check)

    def transcribe_fixture() -> dict[str, Any]:
        if pcm is None:
            raise SmokeFailure("SAPI fixture was unavailable; transcription was not run")
        from agent_platform.config import Settings
        from agent_platform.core.voice_input import FasterWhisperTranscriber, normalize_transcript

        settings = Settings(
            _env_file=None,
            voice_enabled=True,
            voice_model_dir=bundle_root / "models" / "faster-whisper-small",
            voice_cpu_threads=8,
            voice_num_workers=1,
            voice_beam_size=3,
            voice_vad_enabled=True,
        )
        transcript = normalize_transcript(FasterWhisperTranscriber(settings).transcribe(pcm))
        if not transcript:
            raise SmokeFailure("Faster-Whisper returned an empty transcript")
        matched_keywords = [
            keyword for keyword in ("局域网", "交换机", "连接", "设备") if keyword in transcript
        ]
        if not matched_keywords:
            raise SmokeFailure(f"transcript did not preserve any expected keyword: {transcript}")
        return {
            "input_text": ASR_FIXTURE_TEXT,
            "transcript": transcript,
            "matched_keywords": matched_keywords,
            "model": "faster-whisper-small",
            "compute_type": "int8",
        }

    check, _ = _check("asr_faster_whisper_real", transcribe_fixture, bundle_root)
    checks.append(check)

    def cleanup_fixture() -> dict[str, Any]:
        nonlocal pcm
        if pcm is not None:
            pcm[:] = b"\x00" * len(pcm)
            pcm.clear()
        pcm = None
        if fixture_path is not None:
            fixture_path.unlink(missing_ok=True)
            if fixture_path.exists():
                raise SmokeFailure("temporary SAPI WAV could not be deleted")
        return {"temporary_audio_deleted": True}

    check, _ = _check("asr_temporary_audio_cleanup", cleanup_fixture, bundle_root)
    checks.append(check)
    return checks


def _resolve_output(path: Path, bundle_root: Path) -> Path:
    return path if path.is_absolute() else bundle_root / path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("model", "asr", "tts", "all"))
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--agent-url", default="http://127.0.0.1:8000")
    parser.add_argument("--llama-url", default="http://127.0.0.1:8080")
    parser.add_argument("--model-id", default=os.environ.get("LLAMACPP_MODEL_NAME", "local-model"))
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--output", type=Path, default=Path("logs/smoke/smoke-report.json"))
    parser.add_argument("--artifacts-dir", type=Path, default=Path("logs/smoke/tts"))
    args = parser.parse_args(argv)

    bundle_root = args.bundle_root.resolve()
    if not bundle_root.is_dir():
        parser.error("--bundle-root must be an existing directory")
    output_path = _resolve_output(args.output, bundle_root)
    artifacts_dir = _resolve_output(args.artifacts_dir, bundle_root)
    output_relative = _artifact_relative_path(output_path, bundle_root)
    checks: list[dict[str, Any]] = []
    task_context: dict[str, str] | None = None

    if args.phase in {"model", "all"}:
        model_checks, task_context = run_model_phase(
            bundle_root=bundle_root,
            llama_url=args.llama_url,
            agent_url=args.agent_url,
            model_id=args.model_id,
            timeout_seconds=args.timeout_seconds,
        )
        checks.extend(model_checks)
    if args.phase in {"asr", "all"}:
        checks.extend(run_asr_phase(bundle_root=bundle_root, timeout_seconds=args.timeout_seconds))
    if args.phase in {"tts", "all"}:
        checks.extend(
            run_tts_phase(
                bundle_root=bundle_root,
                agent_url=args.agent_url,
                timeout_seconds=args.timeout_seconds,
                artifacts_dir=artifacts_dir,
                task_context=task_context,
            )
        )

    passed = bool(checks) and all(check["passed"] for check in checks)
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "phase": args.phase,
        "model_id": args.model_id if args.phase in {"model", "all"} else None,
        "passed": passed,
        "pass_count": sum(bool(check["passed"]) for check in checks),
        "check_count": len(checks),
        "checks": checks,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report = _sanitize_for_report(report, bundle_root)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "passed": passed,
                "pass_count": report["pass_count"],
                "check_count": report["check_count"],
                "report": output_relative,
            },
            ensure_ascii=False,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
