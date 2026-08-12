"""Validate supervised Ollama switching and knowledge-root reconfiguration."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import httpx


VIEW_ONLY_FIELDS = {"locked_fields", "supervised", "ollama_models", "knowledge_index"}


def _editable(view: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in view.items() if key not in VIEW_ONLY_FIELDS}


def _wait_ready(client: httpx.Client, previous: str | None) -> dict[str, Any]:
    deadline = time.monotonic() + 30.0
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        try:
            last = client.get("/admin/restart-status").json()
            if last.get("state") == "ready" and last.get("completed_at") != previous:
                return last
        except httpx.HTTPError:
            pass
        time.sleep(0.25)
    raise TimeoutError(f"desktop restart did not become ready: {last}")


def _wait_task(client: httpx.Client, task_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        task = client.get(f"/tasks/{task_id}").json()
        if task.get("state") in {"completed", "failed", "cancelled", "awaiting_confirmation"}:
            return task
        time.sleep(0.1)
    raise TimeoutError(f"task did not finish: {task_id}")


def run(base_url: str) -> dict[str, Any]:
    headers = {"X-Session-Id": "desktop-configuration-validation"}
    with httpx.Client(base_url=base_url, headers=headers, timeout=30.0) as client:
        original = _editable(client.get("/admin/settings").json())
        proposed = dict(original)
        proposed["model_provider"] = "ollama"
        proposed["model_name"] = "qwen2.5:3b"
        proposed["knowledge_roots"] = list(reversed(original["knowledge_roots"]))
        previous = client.get("/admin/restart-status").json().get("completed_at")
        client.put("/admin/settings", json=proposed).raise_for_status()
        switched = _wait_ready(client, previous)
        try:
            health = client.get("/health").json()
            capabilities = client.get("/meta/capabilities").json()
            reindex = client.post("/admin/knowledge/reindex").json()
            started = client.post("/tasks", json={"text": "查询知识库：产品保修期是多久？"}).json()
            task = _wait_task(client, started["id"])
            answer = str(((task.get("result") or {}).get("output") or {}).get("answer", ""))
            sources = ((task.get("result") or {}).get("output") or {}).get("sources", [])
            report = {
                "switch": {
                    "restart": switched,
                    "health_provider": health.get("model_provider"),
                    "model_name": capabilities.get("platform", {}).get("model_name"),
                    "ok": health.get("model_provider") == "ollama"
                    and capabilities.get("platform", {}).get("model_name") == "qwen2.5:3b",
                },
                "knowledge": {
                    "roots": capabilities.get("authorized_roots", {}).get("knowledge", []),
                    "reindex": reindex,
                    "task_state": task.get("state"),
                    "answer": answer,
                    "sources": sources,
                    "ok": task.get("state") == "completed" and "两年" in answer and bool(sources),
                },
            }
        finally:
            previous = client.get("/admin/restart-status").json().get("completed_at")
            client.put("/admin/settings", json=original).raise_for_status()
            restored = _wait_ready(client, previous)
        restored_view = client.get("/admin/settings").json()
        report["restore"] = {
            "restart": restored,
            "provider": restored_view["model_provider"],
            "knowledge_roots": restored_view["knowledge_roots"],
            "ok": restored_view["model_provider"] == original["model_provider"]
            and restored_view["knowledge_roots"] == original["knowledge_roots"],
        }
        checks = [report[name]["ok"] for name in ("switch", "knowledge", "restore")]
        report["pass_count"] = sum(checks)
        report["check_count"] = len(checks)
        return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8124")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.base_url)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"pass_count": report["pass_count"], "check_count": report["check_count"]}))


if __name__ == "__main__":
    main()
