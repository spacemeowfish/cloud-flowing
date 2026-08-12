"""Run fixed model and Agent requests from inside one PoC container."""

from __future__ import annotations

import json
import os
import time
from urllib.request import Request, urlopen


def post_json(url: str, payload: dict[str, object], *, timeout: float = 180) -> dict[str, object]:
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def model_throughput() -> tuple[float, int, float]:
    started = time.perf_counter()
    body = post_json(
        "http://127.0.0.1:8080/v1/chat/completions",
        {
            "model": os.environ.get("LLAMACPP_MODEL_NAME", "local-model"),
            "messages": [{"role": "user", "content": "请用约120字说明局域网交换机的作用。"}],
            "temperature": 0,
            "max_tokens": 160,
            "stream": False,
        },
    )
    elapsed = time.perf_counter() - started
    usage = body.get("usage", {}) if isinstance(body.get("usage"), dict) else {}
    completion_tokens = int(usage.get("completion_tokens", 0) or 0)
    timings = body.get("timings", {}) if isinstance(body.get("timings"), dict) else {}
    tokens_per_second = float(timings.get("predicted_per_second", 0) or 0)
    if tokens_per_second <= 0 and completion_tokens:
        tokens_per_second = completion_tokens / elapsed
    return tokens_per_second, completion_tokens, elapsed


def model_ttft() -> float:
    payload = json.dumps(
        {
            "model": os.environ.get("LLAMACPP_MODEL_NAME", "local-model"),
            "messages": [{"role": "user", "content": "用一句话说明什么是人工智能。"}],
            "temperature": 0,
            "max_tokens": 64,
            "stream": True,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = Request(
        "http://127.0.0.1:8080/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    with urlopen(request, timeout=180) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:") or line == "data: [DONE]":
                continue
            chunk = json.loads(line[5:].strip())
            choices = chunk.get("choices", [])
            if choices and str(choices[0].get("delta", {}).get("content", "")):
                return time.perf_counter() - started
    raise RuntimeError("stream completed without a content token")


def submit_agent(text: str) -> tuple[bool, float, str]:
    started = time.perf_counter()
    task = post_json("http://127.0.0.1:8000/tasks", {"text": text})
    task_id = str(task["id"])
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        with urlopen(f"http://127.0.0.1:8000/tasks/{task_id}", timeout=5) as response:
            current = json.loads(response.read().decode("utf-8"))
        state = str(current["state"])
        if state in {"completed", "failed", "cancelled", "awaiting_confirmation"}:
            return state == "completed", time.perf_counter() - started, state
        time.sleep(0.1)
    return False, time.perf_counter() - started, "timeout"


def main() -> None:
    tokens_per_second, completion_tokens, generation_seconds = model_throughput()
    ttft_seconds = model_ttft()
    fixed_requests = (
        "1+1等于多少？",
        "请用一句话说明局域网是什么？",
        "把你好翻译成英文",
        "总结这段：本季度完成了三个项目，分别覆盖知识库、工作流和接口验证。",
        "查询全部待办",
    )
    fixed = []
    for text in fixed_requests:
        success, elapsed, state = submit_agent(text)
        fixed.append({"text": text, "success": success, "seconds": elapsed, "state": state})
    continuous = []
    for index in range(10):
        text = fixed_requests[index % len(fixed_requests)]
        success, elapsed, state = submit_agent(text)
        continuous.append({"index": index + 1, "success": success, "seconds": elapsed, "state": state})
    print(
        json.dumps(
            {
                "tokens_per_second": tokens_per_second,
                "completion_tokens": completion_tokens,
                "generation_seconds": generation_seconds,
                "ttft_seconds": ttft_seconds,
                "fixed_requests": fixed,
                "continuous_successes": sum(int(item["success"]) for item in continuous),
                "continuous_total": len(continuous),
                "continuous_requests": continuous,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
