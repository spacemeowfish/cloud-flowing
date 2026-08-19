"""One-shot smoke against a running serve instance (demo configuration).

Usage: DEVELOPER_PASSWORD=<local .env value> python scripts/smoke_ollama_demo.py
The password is never committed; read it from the environment.
"""

import asyncio
import json
import os
import sys

import httpx

BASE = "http://127.0.0.1:8000"
PASSWORD = os.environ.get("DEVELOPER_PASSWORD", "")


async def wait_state(client, task_id, timeout=90.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        task = (await client.get(f"/tasks/{task_id}")).json()
        if task["state"] in {"completed", "failed", "cancelled"}:
            return task
        await asyncio.sleep(0.25)
    return {"state": "timeout", "id": task_id}


def summarize(task):
    result = task.get("result") or {}
    output = result.get("output") or result
    text = json.dumps(output, ensure_ascii=False)[:300]
    return f"[{task['state']}] error={task.get('error')} result={text}"


async def main() -> int:
    ok = True
    async with httpx.AsyncClient(base_url=BASE, timeout=90) as client:
        health = (await client.get("/health")).json()
        print("health:", health["status"], health["model_provider"])

        cases = [
            ("pre-route reminder", "提醒我5分钟后喝水"),
            ("model schedule", "明天下午3点开项目评审会"),
            ("model knowledge", "帮我看看这段材料说了什么：云湃设备保修期是两年"),
            ("general chat", "珠穆朗玛峰有多高"),
        ]
        for label, text in cases:
            created = await client.post("/tasks", json={"text": text})
            task = await wait_state(client, created.json()["id"])
            print(f"{label}: {summarize(task)}")
            if task["state"] != "completed":
                ok = False

        # A1 smoke: developer login, then an ordinary task from the same cookie jar.
        login = await client.post("/auth/developer/login", json={"password": PASSWORD})
        print("developer login:", login.status_code)
        ok = ok and login.status_code == 200
        created = await client.post("/tasks", json={"text": "提醒我10分钟后站起来活动"})
        task = await wait_state(client, created.json()["id"])
        print("developer-cookie task:", summarize(task))
        ok = ok and task["state"] == "completed"

        cancel = await client.post(f"/tasks/{created.json()['id']}/cancel", json={"reason": "smoke"})
        print("cancel-after-complete:", cancel.status_code, cancel.json().get("state"))

        # B4 smoke: ollama down path is not tested here (server depends on it).
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
