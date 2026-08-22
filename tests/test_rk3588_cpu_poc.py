import json
import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
POC = ROOT / "deployment" / "rk3588" / "docker"


def test_model_lock_pins_official_revisions_and_sha256():
    models = json.loads((POC / "models.lock.json").read_text(encoding="utf-8"))
    assert set(models) == {"qwen", "lfm"}
    assert models["qwen"]["repository"] == "Qwen/Qwen2.5-3B-Instruct-GGUF"
    assert models["lfm"]["repository"] == "LiquidAI/LFM2.5-1.2B-Instruct-GGUF"
    for spec in models.values():
        assert re.fullmatch(r"[0-9a-f]{40}", spec["revision"])
        assert re.fullmatch(r"[0-9a-f]{64}", spec["sha256"])
        assert spec["filename"].endswith(".gguf")


def test_runtime_image_is_single_model_and_has_no_build_toolchain():
    dockerfile = (POC / "Dockerfile.cpu-poc").read_text(encoding="utf-8")
    runtime = dockerfile.split(" AS runtime", 1)[1]
    assert "COPY models/${MODEL_FILE} /opt/models/model.gguf" in runtime
    assert "LLAMACPP_THREADS=4" in runtime
    assert "LLAMACPP_CONTEXT_SIZE=2048" in runtime
    assert "LLAMACPP_MAX_TOKENS=256" in runtime
    assert "AGENT_AUTHORIZED_FILE_ROOTS='[\"/opt/app/data/authorized_files\"]'" in runtime
    assert "AGENT_KNOWLEDGE_ROOTS='[\"/opt/app/data/knowledge\"]'" in runtime
    assert "build-essential" not in runtime
    assert "cmake" not in runtime
    assert "ollama" not in runtime.casefold()
    assert "rknpu" not in runtime.casefold()


def test_two_compose_files_select_distinct_images_and_one_service():
    qwen = yaml.safe_load((POC / "compose.qwen.yml").read_text(encoding="utf-8"))
    lfm = yaml.safe_load((POC / "compose.lfm.yml").read_text(encoding="utf-8"))
    assert set(qwen["services"]) == {"agent"}
    assert set(lfm["services"]) == {"agent"}
    assert qwen["services"]["agent"]["image"] != lfm["services"]["agent"]["image"]
    assert qwen["services"]["agent"]["ports"] == ["8000:8000"]
    # 旧"环境变量开发者密码门"已退役（ADR 0007，RUOYI-AUTH-GATEWAY-001 Phase 6 清理）：
    # compose 不再要求 DEVELOPER_PASSWORD，认证统一由若依网关承担。
    assert "environment" not in qwen["services"]["agent"]
    assert "environment" not in lfm["services"]["agent"]
    assert "DEVELOPER_PASSWORD" not in (POC / "compose.qwen.yml").read_text(encoding="utf-8")
    assert "DEVELOPER_PASSWORD" not in (POC / "compose.lfm.yml").read_text(encoding="utf-8")


def test_profiles_and_automatic_benchmark_match_acceptance_plan():
    profiles = {}
    for name in ("startup", "performance", "pressure"):
        profiles[name] = dict(
            line.split("=", 1)
            for line in (POC / "profiles" / f"{name}.env").read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    assert profiles["startup"]["LLAMACPP_CONTEXT_SIZE"] == "2048"
    assert profiles["startup"]["LLAMACPP_MAX_TOKENS"] == "256"
    assert profiles["performance"]["LLAMACPP_CONTEXT_SIZE"] == "4096"
    assert profiles["performance"]["LLAMACPP_MAX_TOKENS"] == "512"
    assert profiles["pressure"]["LLAMACPP_CONTEXT_SIZE"] == "8192"
    benchmark = (POC / "benchmark_profiles.py").read_text(encoding="utf-8")
    assert "for threads in (4, 6, 8)" in benchmark
    assert "continuous_successes" in benchmark
    assert "peak_temperature_celsius" in benchmark
    assert "system_stall_detected" in benchmark
    assert "fallback_to_2048_after_all_4096_profiles_failed" in benchmark
    assert "Startup profile failed" in benchmark
    assert "selected.env" in benchmark
    assert "--bind-address" in benchmark
    assert 'f"{bind_address}:{port}:8000"' in benchmark
    # 密码门退役后（ADR 0007）：benchmark 不再注入/要求 DEVELOPER_PASSWORD
    assert '"--env", "DEVELOPER_PASSWORD"' not in benchmark
    assert "DEVELOPER_PASSWORD is required" not in benchmark
    install = (POC / "install.sh").read_text(encoding="utf-8")
    assert "board_probe.sh" in install
    assert "benchmark_profiles.py" in install
    assert 'sha256sum "$archive"' in install
    assert "POC_BIND_ADDRESS" in install
    assert "POC_DEVELOPER_PASSWORD" not in install
    build = (POC / "build_images.ps1").read_text(encoding="utf-8")
    assert "SHA256SUMS" in build
    assert "Get-FileHash -Algorithm SHA256" in build
    assert "RK3588-USAGE.md" in build
    client = (POC / "benchmark_client.py").read_text(encoding="utf-8")
    assert "把你好翻译成英文" in client


def test_build_script_creates_independent_single_model_packages():
    build = (POC / "build_images.ps1").read_text(encoding="utf-8")
    assert "[switch]$PackageOnly" in build
    assert '"rk3588-$Name"' in build
    assert "New-ModelPackage" in build
    assert "cloud-flowing-$otherName-rk3588-cpu-poc.tar" in build
    assert "Remove-Item -LiteralPath $otherArchive" in build
    assert "PACKAGE-MANIFEST.txt" in build
    assert '"model=$Name"' in build
    assert "foreach ($name in $names) { New-ModelPackage $name }" in build


def test_runtime_entrypoint_uses_posix_shell_only():
    entrypoint = (POC / "entrypoint.sh").read_text(encoding="utf-8")
    assert entrypoint.startswith("#!/bin/sh\n")
    assert "[[" not in entrypoint
    assert "wait -n" not in entrypoint
    assert "${!" not in entrypoint


def test_serve_cli_does_not_import_evaluation_runtime_eagerly():
    cli = (ROOT / "agent_platform" / "cli.py").read_text(encoding="utf-8")
    module_imports = cli.split("async def _evaluate", 1)[0]
    assert "from agent_platform.core.evaluation_service import EvaluationService" not in module_imports
    assert "    from agent_platform.core.evaluation_service import EvaluationService" in cli
