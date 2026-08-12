"""Generate and validate one real ZipVoice WAV for every configured desktop voice."""

from __future__ import annotations

import argparse
import io
import json
import time
import wave
from pathlib import Path
from typing import Any

import httpx


def _wait_task(client: httpx.Client, task_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        task = client.get(f"/tasks/{task_id}").json()
        if task.get("state") in {"completed", "failed", "cancelled"}:
            return task
        time.sleep(0.1)
    raise TimeoutError(f"task did not finish: {task_id}")


def run(base_url: str) -> dict[str, Any]:
    headers = {"X-Session-Id": "zipvoice-desktop-validation"}
    with httpx.Client(base_url=base_url, headers=headers, timeout=120.0) as client:
        capabilities = client.get("/meta/capabilities").json()
        tts = capabilities["tts"]
        task = client.post("/tasks", json={"text": "1+1等于多少？"}).json()
        task = _wait_task(client, task["id"])
        if task.get("state") != "completed":
            raise RuntimeError(f"source task failed: {task}")

        results = []
        for voice in tts.get("voices", []):
            voice_id = str(voice["id"])
            started = time.perf_counter()
            response = client.post(f"/tasks/{task['id']}/speech", json={"voice_id": voice_id})
            elapsed = time.perf_counter() - started
            response.raise_for_status()
            artifact = response.json()
            audio = client.get(artifact["audio_url"]).content
            with wave.open(io.BytesIO(audio), "rb") as wav:
                channels = wav.getnchannels()
                sample_width = wav.getsampwidth()
                sample_rate = wav.getframerate()
                frames = wav.getnframes()
            ok = (
                channels == 1
                and sample_width == 2
                and sample_rate == artifact["sample_rate"]
                and frames > 0
                and artifact["duration_seconds"] > 0
            )
            results.append(
                {
                    "voice_id": voice_id,
                    "voice_label": artifact["voice_label"],
                    "elapsed_seconds": round(elapsed, 3),
                    "duration_seconds": artifact["duration_seconds"],
                    "sample_rate": sample_rate,
                    "channels": channels,
                    "sample_width_bytes": sample_width,
                    "wav_bytes": len(audio),
                    "ok": ok,
                }
            )
        return {
            "provider": tts.get("provider"),
            "source_text": "1+1 = 2",
            "results": results,
            "pass_count": sum(bool(item["ok"]) for item in results),
            "voice_count": len(results),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8124")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.base_url)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"pass_count": report["pass_count"], "voice_count": report["voice_count"]}))


if __name__ == "__main__":
    main()
