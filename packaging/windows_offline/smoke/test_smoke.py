from __future__ import annotations

import io
import importlib.util
import unittest
import wave
from pathlib import Path


_SMOKE_PATH = Path(__file__).with_name("smoke.py")
_SMOKE_SPEC = importlib.util.spec_from_file_location("cloud_flowing_offline_smoke", _SMOKE_PATH)
assert _SMOKE_SPEC is not None and _SMOKE_SPEC.loader is not None
smoke = importlib.util.module_from_spec(_SMOKE_SPEC)
_SMOKE_SPEC.loader.exec_module(smoke)


def _wav_bytes() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(b"\x01\x00" * 1600)
    return buffer.getvalue()


class SmokePureFunctionTests(unittest.TestCase):
    def test_validate_wav_accepts_nonempty_pcm16_mono(self) -> None:
        details = smoke._validate_wav_bytes(_wav_bytes())
        self.assertEqual(details["channels"], 1)
        self.assertEqual(details["sample_rate"], 16000)
        self.assertEqual(details["duration_seconds"], 0.1)

    def test_extract_agent_answer_requires_general_chat(self) -> None:
        task = {
            "result": {
                "tool_name": "general_chat",
                "output": {"answer": "交换机连接局域网内的设备。"},
            }
        }
        self.assertEqual(smoke._extract_agent_answer(task), "交换机连接局域网内的设备。")
        task["result"]["tool_name"] = "knowledge_query"
        with self.assertRaises(smoke.SmokeFailure):
            smoke._extract_agent_answer(task)

    def test_error_redaction_removes_windows_paths(self) -> None:
        root = Path(r"D:\offline\cloud-flowing")
        redacted = smoke._redact_local_paths(
            r"failed at D:\offline\cloud-flowing\models\qwen.gguf and C:\Users\tester\audio.wav",
            root,
        )
        self.assertNotIn("D:\\offline", redacted)
        self.assertNotIn("C:\\Users", redacted)
        self.assertIn("<local-path>", redacted)

    def test_report_sanitizer_recurses_into_nested_values(self) -> None:
        root = Path(r"D:\offline\cloud-flowing")
        sanitized = smoke._sanitize_for_report(
            {"checks": [{"answer": r"see C:\Users\tester\answer.txt"}]}, root
        )
        self.assertNotIn("C:\\Users", sanitized["checks"][0]["answer"])

    def test_artifacts_must_stay_below_bundle_root(self) -> None:
        root = Path(r"D:\offline\cloud-flowing")
        self.assertEqual(
            smoke._artifact_relative_path(root / "logs" / "smoke.json", root),
            "logs/smoke.json",
        )
        with self.assertRaises(smoke.SmokeFailure):
            smoke._artifact_relative_path(Path(r"C:\outside\smoke.json"), root)


if __name__ == "__main__":
    unittest.main()
