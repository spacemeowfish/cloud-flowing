"""Exercise supervised settings, Toast, and authorized Windows file opening."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import httpx


VIEW_ONLY_FIELDS = {"locked_fields", "supervised", "ollama_models", "knowledge_index"}
STOP_STATES = {"completed", "failed", "cancelled", "awaiting_confirmation"}


def _editable(settings: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in settings.items() if key not in VIEW_ONLY_FIELDS}


def _wait_ready(client: httpx.Client, previous_completed: str | None, timeout: float = 30.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        try:
            last = client.get("/admin/restart-status").json()
            if last.get("state") == "ready" and last.get("completed_at") != previous_completed:
                return last
        except httpx.HTTPError:
            pass
        time.sleep(0.25)
    raise TimeoutError(f"desktop restart did not become ready: {last}")


def _task(client: httpx.Client, text: str) -> dict[str, Any]:
    task = client.post("/tasks", json={"text": text}).json()
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        task = client.get(f"/tasks/{task['id']}").json()
        if task.get("state") in STOP_STATES:
            return task
        time.sleep(0.1)
    raise TimeoutError(f"task did not finish: {task['id']}")


def _confirm(client: httpx.Client, task: dict[str, Any], selected_path: str) -> dict[str, Any]:
    response = client.post(
        f"/tasks/{task['id']}/confirm",
        json={"approved": True, "arguments": {"selected_path": selected_path}},
    )
    if response.status_code >= 400:
        return {"state": "http_error", "status_code": response.status_code, "response": response.json()}
    return response.json()


def _receipt(task: dict[str, Any]) -> dict[str, Any]:
    result = task.get("result") or {}
    if result.get("type") == "candidate_confirmation":
        return (result.get("receipt") or {}).get("output") or {}
    return result.get("output") or {}


def run(base_url: str) -> dict[str, Any]:
    headers = {"X-Session-Id": "windows-desktop-validation"}
    with httpx.Client(base_url=base_url, headers=headers, timeout=30.0) as client:
        original_view = client.get("/admin/settings").json()
        original = _editable(original_view)
        enabled = dict(original)
        enabled["file_open_enabled"] = True
        before = client.get("/admin/restart-status").json().get("completed_at")
        enable_response = client.put("/admin/settings", json=enabled)
        enable_response.raise_for_status()
        enabled_ready = _wait_ready(client, before)

        report: dict[str, Any] = {}
        try:
            notification = client.post("/admin/notifications/test")
            notification.raise_for_status()
            report["notification"] = notification.json()

            unique = _task(client, "查找并打开文件：冒烟测试报告_20260802")
            unique_receipt = _receipt(unique)
            report["unique_candidate"] = {
                "state": unique.get("state"),
                "receipt": unique_receipt,
                "ok": unique.get("state") == "completed"
                and unique_receipt.get("process_status") == "shell_request_accepted",
            }

            multiple = _task(client, "查找并打开文件：项目周报")
            multiple_receipt = _receipt(multiple)
            candidates = multiple_receipt.get("candidates") or []
            report["multiple_candidates"] = {
                "state": multiple.get("state"),
                "candidate_count": len(candidates),
                "candidates": candidates,
                "ok": multiple.get("state") == "awaiting_confirmation" and len(candidates) > 1,
            }

            unauthorized = _confirm(client, multiple, str(Path.home() / "outside-authorized-root.txt"))
            report["unauthorized_selection"] = {
                "state": unauthorized.get("state"),
                "error": unauthorized.get("error") or unauthorized.get("response"),
                "ok": unauthorized.get("state") in {"failed", "http_error"},
            }

            valid_multiple = _task(client, "查找并打开文件：项目周报")
            valid_candidates = _receipt(valid_multiple).get("candidates") or []
            selected = str(valid_candidates[0]["path"]) if valid_candidates else ""
            confirmed = _confirm(client, valid_multiple, selected) if selected else {"state": "no_candidate"}
            confirmed_receipt = _receipt(confirmed)
            report["confirmed_candidate"] = {
                "state": confirmed.get("state"),
                "selected_name": Path(selected).name if selected else None,
                "receipt": confirmed_receipt,
                "ok": confirmed.get("state") == "completed"
                and confirmed_receipt.get("process_status") == "shell_request_accepted",
            }
        finally:
            current = client.get("/admin/restart-status").json().get("completed_at")
            restore_response = client.put("/admin/settings", json=original)
            restore_response.raise_for_status()
            restored_ready = _wait_ready(client, current)

        report["supervised_restart"] = {
            "enabled_ready": enabled_ready,
            "restored_ready": restored_ready,
            "file_open_restored": client.get("/admin/settings").json()["file_open_enabled"] is False,
        }
        checks = [item.get("ok") for item in report.values() if isinstance(item, dict) and "ok" in item]
        report["pass_count"] = sum(value is True for value in checks)
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
