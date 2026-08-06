"""Wait for the RKLLM and Agent HTTP readiness contracts using the standard library."""

from __future__ import annotations

import argparse
import json
import time
from urllib.error import URLError
from urllib.request import urlopen


def read_json(url: str, timeout: float = 2.0) -> dict[str, object]:
    with urlopen(url, timeout=timeout) as response:  # noqa: S310 - deployment URLs are operator supplied.
        if response.status != 200:
            raise RuntimeError(f"{url} returned HTTP {response.status}")
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"{url} did not return a JSON object")
    return payload


def check_rkllm(base_url: str) -> None:
    payload = read_json(f"{base_url.rstrip('/')}/models")
    data = payload.get("data")
    if payload.get("object") != "list" or not isinstance(data, list) or not data:
        raise RuntimeError("RKLLM /models response does not match the frozen readiness contract")


def check_agent(base_url: str) -> None:
    payload = read_json(f"{base_url.rstrip('/')}/health")
    if payload.get("status") != "ok":
        raise RuntimeError("Agent /health did not report status=ok")


def wait_until_ready(checks: list[tuple[str, str]], wait_seconds: float) -> None:
    deadline = time.monotonic() + wait_seconds
    last_error: Exception | None = None
    while time.monotonic() <= deadline:
        try:
            for kind, url in checks:
                check_rkllm(url) if kind == "rkllm" else check_agent(url)
            return
        except (RuntimeError, URLError, TimeoutError, ValueError) as exc:
            last_error = exc
            time.sleep(1)
    raise SystemExit(f"readiness check failed after {wait_seconds:g}s: {last_error}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rkllm-url", default="http://127.0.0.1:8080/v1")
    parser.add_argument("--agent-url", default="http://127.0.0.1:8000")
    parser.add_argument("--rkllm-only", action="store_true")
    parser.add_argument("--wait", type=float, default=60)
    args = parser.parse_args()
    checks = [("rkllm", args.rkllm_url)]
    if not args.rkllm_only:
        checks.append(("agent", args.agent_url))
    wait_until_ready(checks, args.wait)
    print("readiness contracts passed")


if __name__ == "__main__":
    main()


__all__ = ["check_agent", "check_rkllm", "read_json", "wait_until_ready"]
