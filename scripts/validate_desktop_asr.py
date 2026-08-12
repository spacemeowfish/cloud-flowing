"""Transcribe fixed Windows desktop ASR fixtures with the real Faster-Whisper model."""

from __future__ import annotations

import argparse
import json
import time
import wave
from pathlib import Path

from agent_platform.config import Settings
from agent_platform.core.voice_input import FasterWhisperTranscriber, normalize_transcript


FIXTURES = {
    "math": {
        "text": "1+1等于多少",
        "audio": "01-math.wav",
        "keyword_groups": [["1", "一"], ["等于"], ["多少"]],
    },
    "reminder": {
        "text": "一分钟后提醒我检查服务",
        "audio": "02-reminder.wav",
        "keyword_groups": [["一分钟", "1分钟"], ["提醒"], ["检查服务"]],
    },
    "knowledge": {
        "text": "查询产品保修期",
        "audio": "03-knowledge.wav",
        "keyword_groups": [["查询"], ["产品"], ["保修期"]],
    },
    "tone": {
        "text": "调整为正式语气",
        "audio": "04-tone.wav",
        "keyword_groups": [["调整"], ["正式"], ["语气"]],
    },
    "schedule": {
        "text": "创建明天下午两点项目例会",
        "audio": "05-schedule.wav",
        "keyword_groups": [["创建"], ["明天"], ["下午两点", "下午2点"], ["项目例会"]],
    },
}


def _pcm16(path: Path) -> tuple[bytes, float]:
    with wave.open(str(path), "rb") as source:
        if source.getnchannels() != 1 or source.getsampwidth() != 2 or source.getframerate() != 16000:
            raise ValueError(f"ASR fixture must be mono 16 kHz PCM16: {path}")
        frames = source.readframes(source.getnframes())
        return frames, source.getnframes() / source.getframerate()


def _missing_groups(transcript: str, groups: list[list[str]]) -> list[list[str]]:
    return [group for group in groups if not any(candidate in transcript for candidate in group)]


def run(audio_dir: Path, model_dir: Path) -> dict[str, object]:
    settings = Settings(
        _env_file=None,
        voice_enabled=True,
        voice_model_dir=model_dir,
        voice_cpu_threads=8,
        voice_num_workers=1,
        voice_beam_size=3,
        voice_vad_enabled=True,
    )
    transcriber = FasterWhisperTranscriber(settings)
    results = []
    for fixture_id, fixture in FIXTURES.items():
        path = audio_dir / str(fixture["audio"])
        started = time.perf_counter()
        groups = [[str(candidate) for candidate in group] for group in fixture["keyword_groups"]]
        try:
            pcm, duration = _pcm16(path)
            transcript = normalize_transcript(transcriber.transcribe(pcm))
            missing = _missing_groups(transcript, groups)
            error = None
        except Exception as exc:
            transcript = ""
            duration = 0.0
            missing = groups
            error = f"{type(exc).__name__}: {exc}"
        results.append(
            {
                "id": fixture_id,
                "expected": fixture["text"],
                "audio": str(fixture["audio"]),
                "audio_duration_seconds": round(duration, 3),
                "transcript": transcript,
                "missing_keyword_groups": missing,
                "elapsed_seconds": round(time.perf_counter() - started, 3),
                "ok": not missing and error is None,
                "error": error,
            }
        )
    return {
        "model_dir": str(model_dir),
        "backend": "faster-whisper",
        "device": "cpu",
        "compute_type": "int8",
        "fixture_source": "Windows SAPI Microsoft Huihui Desktop, 16 kHz mono PCM16",
        "results": results,
        "pass_count": sum(bool(item["ok"]) for item in results),
        "case_count": len(results),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio-dir", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.audio_dir, args.model_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"pass_count": report["pass_count"], "case_count": report["case_count"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
