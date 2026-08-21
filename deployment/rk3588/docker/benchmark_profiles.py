"""Serially benchmark startup, 4/6/8-thread performance, and 8192-context pressure."""

from __future__ import annotations

import argparse
from collections.abc import Callable
import json
import os
import re
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


CONTAINER_NAME = "cloud-flowing-poc"


def command(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=check, text=True, encoding="utf-8", errors="replace", capture_output=True)


def remove_container(name: str) -> None:
    command("docker", "rm", "--force", name, check=False)


def start_container(
    image: str,
    name: str,
    port: int,
    bind_address: str,
    profile: dict[str, int],
    *,
    on_started: Callable[[], None] | None = None,
) -> tuple[float, float]:
    remove_container(name)
    started = time.perf_counter()
    args = [
        "docker", "run", "--detach", "--name", name,
        "--publish", f"{bind_address}:{port}:8000",
        "--env", f"LLAMACPP_THREADS={profile['threads']}",
        "--env", f"LLAMACPP_CONTEXT_SIZE={profile['context_size']}",
        "--env", f"LLAMACPP_MAX_TOKENS={profile['max_tokens']}",
        "--env", f"LLAMACPP_BATCH_SIZE={profile['batch_size']}",
        "--env", f"LLAMACPP_PARALLEL={profile['parallel']}",
        "--volume", "cloud-flowing-poc-data:/opt/app/data",
        "--volume", "cloud-flowing-poc-logs:/opt/app/logs",
        image,
    ]
    command(*args)
    if on_started is not None:
        on_started()
    deadline = time.monotonic() + 420
    model_ready_seconds: float | None = None
    while time.monotonic() < deadline:
        if model_ready_seconds is None:
            model_health = command(
                "docker", "exec", name, "python", "-c",
                "from urllib.request import urlopen; assert urlopen('http://127.0.0.1:8080/health', timeout=2).status == 200",
                check=False,
            )
            if model_health.returncode == 0:
                model_ready_seconds = time.perf_counter() - started
        try:
            with urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
                if response.status == 200:
                    agent_ready_seconds = time.perf_counter() - started
                    return model_ready_seconds or agent_ready_seconds, agent_ready_seconds
        except (URLError, TimeoutError, ConnectionError):
            pass
        state = command("docker", "inspect", "--format", "{{.State.Status}}", name, check=False).stdout.strip()
        if state in {"exited", "dead"}:
            logs = command("docker", "logs", "--tail", "80", name, check=False)
            raise RuntimeError(f"container exited during load:\n{logs.stdout}\n{logs.stderr}")
        time.sleep(1)
    raise TimeoutError("container did not become healthy within 420 seconds")


def parse_bytes(value: str) -> int:
    match = re.match(r"\s*([0-9.]+)\s*([KMGTP]?i?B)", value)
    if match is None:
        return 0
    units = {"B": 1, "KB": 1000, "MB": 1000**2, "GB": 1000**3, "KiB": 1024, "MiB": 1024**2, "GiB": 1024**3}
    return int(float(match.group(1)) * units.get(match.group(2), 1))


def temperature_celsius() -> float | None:
    values: list[float] = []
    for path in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
        try:
            raw = float(path.read_text(encoding="ascii").strip())
            values.append(raw / 1000 if raw > 1000 else raw)
        except (OSError, ValueError):
            continue
    return max(values) if values else None


def monitor_container(name: str, stop: threading.Event, metrics: dict[str, float | int | None]) -> None:
    last_sample = time.monotonic()
    while not stop.wait(0.5):
        sampled_at = time.monotonic()
        metrics["max_monitor_gap_seconds"] = max(
            float(metrics["max_monitor_gap_seconds"] or 0), sampled_at - last_sample
        )
        last_sample = sampled_at
        result = command("docker", "stats", "--no-stream", "--format", "{{json .}}", name, check=False)
        if result.returncode == 0 and result.stdout.strip():
            try:
                body = json.loads(result.stdout.splitlines()[-1])
                cpu = float(str(body.get("CPUPerc", "0")).rstrip("%") or 0)
                memory = parse_bytes(str(body.get("MemUsage", "0 B")).split("/")[0])
                metrics["peak_cpu_percent"] = max(float(metrics["peak_cpu_percent"] or 0), cpu)
                metrics["peak_memory_bytes"] = max(int(metrics["peak_memory_bytes"] or 0), memory)
            except (ValueError, json.JSONDecodeError):
                pass
        temperature = temperature_celsius()
        if temperature is not None:
            metrics["peak_temperature_celsius"] = max(
                float(metrics["peak_temperature_celsius"] or temperature), temperature
            )


def benchmark_one(
    image: str,
    port: int,
    bind_address: str,
    label: str,
    profile: dict[str, int],
) -> dict[str, object]:
    name = f"cloud-flowing-bench-{label}"
    metrics: dict[str, float | int | None] = {
        "peak_cpu_percent": 0.0,
        "peak_memory_bytes": 0,
        "peak_temperature_celsius": temperature_celsius(),
        "max_monitor_gap_seconds": 0.0,
    }
    stop = threading.Event()
    monitor: threading.Thread | None = None
    result: dict[str, object] = {"label": label, "profile": profile, "passed": False}
    try:
        monitor = threading.Thread(target=monitor_container, args=(name, stop, metrics), daemon=True)
        model_ready, agent_ready = start_container(
            image, name, port, bind_address, profile, on_started=monitor.start
        )
        result["model_load_seconds"] = model_ready
        result["agent_ready_seconds"] = agent_ready
        client = command("docker", "exec", name, "python", "/opt/poc/benchmark_client.py", check=False)
        if client.returncode != 0:
            result["error"] = (client.stderr or client.stdout)[-4000:]
        else:
            client_result = json.loads(client.stdout.splitlines()[-1])
            result.update(client_result)
            result["passed"] = (
                int(client_result.get("continuous_successes", 0)) == 10
                and all(bool(item.get("success")) for item in client_result.get("fixed_requests", []))
            )
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        stop.set()
        if monitor is not None:
            monitor.join(timeout=3)
        inspect = command("docker", "inspect", "--format", "{{json .State}}", name, check=False)
        if inspect.returncode == 0 and inspect.stdout.strip():
            state = json.loads(inspect.stdout)
            result["oom_killed"] = bool(state.get("OOMKilled"))
            result["container_exit_code"] = int(state.get("ExitCode", 0))
        else:
            result["oom_killed"] = False
        result.update(metrics)
        result["system_stall_detected"] = float(result.get("max_monitor_gap_seconds", 0) or 0) > 5.0
        if result.get("oom_killed"):
            result["passed"] = False
        if result.get("system_stall_detected"):
            result["passed"] = False
        result["logs_tail"] = command("docker", "logs", "--tail", "40", name, check=False).stderr[-4000:]
        remove_container(name)
    return result


def write_env(path: Path, profile: dict[str, int]) -> None:
    path.write_text(
        "\n".join(
            (
                f"LLAMACPP_THREADS={profile['threads']}",
                f"LLAMACPP_CONTEXT_SIZE={profile['context_size']}",
                f"LLAMACPP_MAX_TOKENS={profile['max_tokens']}",
                f"LLAMACPP_BATCH_SIZE={profile['batch_size']}",
                f"LLAMACPP_PARALLEL={profile['parallel']}",
                "",
            )
        ),
        encoding="utf-8",
    )


def main() -> None:
    # 旧"开发者密码门"已退役（ADR 0007，RUOYI-AUTH-GATEWAY-001）：容器不再要求密码环境变量，
    # 认证由若依网关承担（见 deployment/ruoyi-gateway/）。
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--bind-address", choices=("127.0.0.1", "0.0.0.0"), default="127.0.0.1")
    parser.add_argument("--output", type=Path, default=Path("rk3588-results"))
    parser.add_argument("--skip-pressure", action="store_true")
    parser.add_argument("--no-start-selected", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    remove_container(CONTAINER_NAME)

    startup = {"threads": 4, "context_size": 2048, "max_tokens": 256, "batch_size": 256, "parallel": 1}
    startup_result = benchmark_one(args.image, args.port, args.bind_address, "startup", startup)
    if not startup_result.get("passed"):
        report = {
            "generated_at": datetime.now(UTC).isoformat(),
            "image": args.image,
            "startup": startup_result,
            "performance": [],
            "selection_rule": "startup profile must pass before performance testing",
        }
        (args.output / "benchmark-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        raise SystemExit("Startup profile failed; inspect benchmark-report.json")
    performance = []
    for threads in (4, 6, 8):
        profile = {"threads": threads, "context_size": 4096, "max_tokens": 512, "batch_size": 512, "parallel": 1}
        performance.append(
            benchmark_one(args.image, args.port, args.bind_address, f"performance-{threads}", profile)
        )

    candidates = [
        item
        for item in performance
        if item.get("passed")
        and not item.get("oom_killed")
        and not item.get("system_stall_detected")
    ]
    if candidates:
        best = max(candidates, key=lambda item: float(item.get("tokens_per_second", 0)))
        selection_basis = "best_stable_4096_profile"
    else:
        best = startup_result
        selection_basis = "fallback_to_2048_after_all_4096_profiles_failed"
    selected = dict(best["profile"])
    pressure = None
    if not args.skip_pressure:
        pressure_profile = {**selected, "context_size": 8192, "max_tokens": 512}
        pressure = benchmark_one(args.image, args.port, args.bind_address, "pressure", pressure_profile)

    selected_path = args.output / "selected.env"
    write_env(selected_path, selected)
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "image": args.image,
        "startup": startup_result,
        "performance": performance,
        "selected_profile": selected,
        "selection_basis": selection_basis,
        "pressure": pressure,
        "selection_rule": "highest tokens_per_second with 10/10 success, no OOM, no detected >5s monitor stall, and all fixed Agent requests completed; otherwise startup 2048 fallback",
    }
    (args.output / "benchmark-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if not args.no_start_selected:
        start_container(args.image, CONTAINER_NAME, args.port, args.bind_address, selected)
        command("docker", "update", "--restart", "unless-stopped", CONTAINER_NAME)
    print(json.dumps({"selected_env": str(selected_path), "report": str(args.output / 'benchmark-report.json'), "selected": selected}, ensure_ascii=False))


if __name__ == "__main__":
    main()
