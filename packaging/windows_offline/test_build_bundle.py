from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_bundle import (  # noqa: E402
    BuildError,
    as_relative_bundle_path,
    bundle_configuration,
    copy_tree_filtered,
    ensure_wheelhouse,
    models_configuration,
    package_status,
    patch_embedded_python,
    redistribution_decision,
    resolve_source_commit,
    scan_metadata_for_private_paths,
    should_copy_source,
)


def test_relative_bundle_paths_reject_absolute_and_traversal() -> None:
    assert as_relative_bundle_path("models/a.gguf") == "models/a.gguf"
    for value in ("C:\\models\\a.gguf", "../a.gguf", "/models/a.gguf", "models/../a.gguf"):
        with pytest.raises(BuildError):
            as_relative_bundle_path(value)


def test_redistribution_gate_refuses_blocked_and_requires_assertion() -> None:
    assets = {
        "ok": {"redistribution": {"status": "allowed", "reason": "ok"}},
        "conditional": {"redistribution": {"status": "conditional", "assertion": "approved", "reason": "needs proof"}},
        "blocked": {"redistribution": {"status": "blocked", "reason": "not licensed"}},
    }
    with pytest.raises(BuildError, match="blocked"):
        redistribution_decision(assets, ("ok", "blocked"), "distributable", {})
    assert redistribution_decision(assets, ("conditional",), "distributable", {"approved": True}) == (True, [])
    allowed, reasons = redistribution_decision(assets, ("blocked",), "local-validation", {})
    assert not allowed
    assert reasons == ["blocked: not licensed"]


def test_runtime_configs_are_relative_and_require_model_acceptance() -> None:
    bundle = bundle_configuration()
    assert bundle["app_root"] == "app"
    assert bundle["paths"]["whisper_model"] == "models/faster-whisper-small"
    assert bundle["runtime"]["python"] == "runtime/python/python.exe"
    models = models_configuration()
    assert models["default_model"] == "qwen"
    assert {model["id"] for model in models["models"]} == {"qwen", "lfm"}
    assert all(model["license_acknowledged"] is False for model in models["models"])
    assert all(model["required_acknowledgement"] for model in models["models"])


def test_embedded_python_path_includes_bundle_app(tmp_path: Path) -> None:
    pth = tmp_path / "python312._pth"
    pth.write_text("python312.zip\n.\n#import site\n", encoding="utf-8")
    patch_embedded_python(tmp_path)
    lines = pth.read_text(encoding="utf-8").splitlines()
    assert "Lib\\site-packages" in lines
    assert "..\\..\\app" in lines
    assert "import site" in lines


def test_source_filter_excludes_private_and_build_state() -> None:
    assert should_copy_source(Path("agent_platform/static/app.js"))
    assert should_copy_source(Path("agent_platform/models/admin.py"))
    assert not should_copy_source(Path("models/qwen.gguf"))
    assert not should_copy_source(Path("tests/test_api.py"))
    assert not should_copy_source(Path("agent_platform/__pycache__/x.pyc"))
    assert not should_copy_source(Path("data/agent.db"))
    assert not should_copy_source(Path(".env"))
    assert not should_copy_source(Path("api-key.txt"))


def test_zipvoice_runtime_copy_excludes_reference_examples(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "test_wavs").mkdir(parents=True)
    (source / "decoder.int8.onnx").write_bytes(b"model")
    (source / "test_wavs" / "leijun-1.wav").write_bytes(b"not-runtime-data")
    destination = tmp_path / "destination"

    copy_tree_filtered(source, destination, ignored_names=("test_wavs",))

    assert (destination / "decoder.int8.onnx").read_bytes() == b"model"
    assert not (destination / "test_wavs").exists()


def test_wheelhouse_matches_normalized_distribution_names(tmp_path: Path) -> None:
    (tmp_path / "annotated_doc-0.0.4-py3-none-any.whl").touch()
    (tmp_path / "python_dotenv-1.2.2-py3-none-any.whl").touch()
    ensure_wheelhouse(tmp_path, ["annotated-doc==0.0.4", "python-dotenv==1.2.2"])

    (tmp_path / "av-18.0.0-cp311-abi3-win_amd64.whl").touch()
    with pytest.raises(BuildError, match="prohibited PyAV"):
        ensure_wheelhouse(tmp_path, ["annotated-doc==0.0.4"])


def test_package_status_and_private_path_scan(tmp_path: Path) -> None:
    status = package_status("local-validation", ["qwen: blocked"])
    assert status["status"] == "NON_DISTRIBUTABLE_LOCAL_VALIDATION"
    assert status["redistributable"] is False
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "bundle.json").write_text(json.dumps({"path": "models/a.gguf"}), encoding="utf-8")
    (tmp_path / "INSTALL.md").write_text("Open http://127.0.0.1:8000/", encoding="utf-8")
    scan_metadata_for_private_paths(tmp_path)
    (tmp_path / "BUILD-METADATA.json").write_text('{"path":"C:\\\\Users\\\\tester"}', encoding="utf-8")
    with pytest.raises(BuildError, match="absolute path"):
        scan_metadata_for_private_paths(tmp_path)


def test_source_commit_requires_full_object_id() -> None:
    expected = "a" * 40
    assert resolve_source_commit(Path.cwd(), expected.upper()) == expected
    with pytest.raises(BuildError, match="40-character"):
        resolve_source_commit(Path.cwd(), "1053a53")


def test_runtime_serializes_path_lists_as_json_arrays() -> None:
    common = (Path(__file__).parent / "runtime" / "Common.ps1").read_text(encoding="ascii")
    assert "ConvertTo-Json -InputObject $authorizedResolved -Compress" in common
    assert "ConvertTo-Json -InputObject $knowledgeResolved -Compress" in common
