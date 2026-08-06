from pathlib import Path

import pytest

from deployment.rk3588.export_rkllm import PIN_SENTINEL, load_build_config
from deployment.rk3588.generate_calibration import EXPECTED_CATEGORIES, load_seed_prompts, rendered_prompts
from deployment.rk3588.prepare_vendor_server import FREQ_EXPRESSION, HOST_EXPRESSION, PORT_EXPRESSION, patch_server_source


ROOT = Path("deployment/rk3588")


def test_calibration_seed_covers_every_intent_without_duplicate_ids():
    seeds = load_seed_prompts(ROOT / "calibration_prompts.json")
    assert len(seeds) == 28
    assert {item["category"] for item in seeds} == EXPECTED_CATEGORIES
    assert len({item["id"] for item in seeds}) == len(seeds)
    prompts = rendered_prompts(seeds)
    assert all("CURRENT_CONVERSATION_JSON:" in prompt for _, prompt in prompts)


def test_w8a8_build_config_is_valid_but_requires_revision_before_real_export():
    path = ROOT / "model-build-config.json"
    config = load_build_config(path, require_pinned_revision=False)
    assert config["source_model_revision"] == PIN_SENTINEL
    assert config["quantized_dtype"] == "W8A8"
    assert config["quantized_algorithm"] == "normal"
    assert config["num_npu_core"] == 3
    with pytest.raises(ValueError, match="pin source_model_revision"):
        load_build_config(path)


def test_prepare_vendor_server_patches_only_expected_runtime_boundaries():
    source = """import os
import subprocess

class App:
    def run(self, **kwargs):
        pass

app = App()
command = "sudo bash fix_freq_rk3588.sh"
subprocess.run(command, shell=True)
app.run(host='0.0.0.0', port=8080, threaded=False, debug=False)
"""
    patched = patch_server_source(source)
    assert HOST_EXPRESSION in patched
    assert PORT_EXPRESSION in patched
    assert FREQ_EXPRESSION in patched
    assert "host='0.0.0.0'" not in patched


def test_prepare_vendor_server_rejects_unexpected_upstream_shape():
    with pytest.raises(ValueError, match="exactly one"):
        patch_server_source("import os\nimport subprocess\n")


def test_systemd_units_and_environment_preserve_localhost_and_serial_defaults():
    environment = (ROOT / ".env.rk3588.example").read_text(encoding="utf-8")
    rkllm_unit = (ROOT / "systemd/rkllm-server.service").read_text(encoding="utf-8")
    agent_unit = (ROOT / "systemd/agent-platform.service").read_text(encoding="utf-8")
    assert "RKLLM_SERVER_HOST=127.0.0.1" in environment
    assert "RKLLM_MAX_CONCURRENCY=1" in environment
    assert "MODEL_FALLBACK_ENABLED=false" in environment
    assert "flask_server_local.py" in rkllm_unit
    assert "RKLLM_ALLOW_INPROCESS_FREQ=0" in rkllm_unit
    assert "Requires=rkllm-server.service" in agent_unit
