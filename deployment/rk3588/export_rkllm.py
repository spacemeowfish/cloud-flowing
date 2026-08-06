"""Build a pinned W8A8 RKLLM artifact and write a reproducibility manifest."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path


PIN_SENTINEL = "PIN_EXACT_HUGGINGFACE_COMMIT_BEFORE_EXPORT"


def load_build_config(path: Path, *, require_pinned_revision: bool = True) -> dict[str, object]:
    config = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "schema_version",
        "source_model_id",
        "source_model_revision",
        "target_platform",
        "quantized_dtype",
        "quantized_algorithm",
        "optimization_level",
        "num_npu_core",
        "max_context",
        "hybrid_rate",
        "load_device",
        "load_dtype",
    }
    if not isinstance(config, dict) or set(config) != expected:
        raise ValueError("model build config fields do not match schema version 1")
    if config["quantized_dtype"] != "W8A8" or config["quantized_algorithm"] != "normal":
        raise ValueError("the accepted baseline is W8A8 with the normal quantization algorithm")
    if config["target_platform"] != "RK3588" or config["num_npu_core"] != 3:
        raise ValueError("the accepted target is RK3588 with three NPU cores")
    if require_pinned_revision and config["source_model_revision"] == PIN_SENTINEL:
        raise ValueError("pin source_model_revision to an exact Hugging Face commit before export")
    return config


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not-installed"


def main() -> None:
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--dataset", type=Path, default=root / "data_quant.json")
    parser.add_argument("--config", type=Path, default=root / "model-build-config.json")
    parser.add_argument("--output", type=Path, default=root / "qwen2.5-3b-instruct-w8a8-rk3588.rkllm")
    parser.add_argument("--manifest", type=Path, default=root / "model-manifest.json")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()

    config = load_build_config(args.config, require_pinned_revision=not args.validate_only)
    if args.validate_only:
        print(json.dumps({"config": config, "config_sha256": sha256(args.config)}, indent=2))
        return
    if args.model_dir is None:
        parser.error("--model-dir is required unless --validate-only is used")
    if not args.model_dir.is_dir():
        raise SystemExit(f"model directory does not exist: {args.model_dir}")
    if not args.dataset.is_file():
        raise SystemExit(f"calibration dataset does not exist: {args.dataset}")

    try:
        from rkllm.api import RKLLM
    except ImportError as exc:
        raise SystemExit("Install the pinned rkllm-toolkit package in the conversion environment") from exc

    llm = RKLLM()
    ret = llm.load_huggingface(
        model=str(args.model_dir),
        model_lora=None,
        device=config["load_device"],
        dtype=config["load_dtype"],
        custom_config=None,
        load_weight=True,
    )
    if ret != 0:
        raise SystemExit(f"RKLLM model load failed with code {ret}")
    ret = llm.build(
        do_quantization=True,
        optimization_level=config["optimization_level"],
        quantized_dtype=config["quantized_dtype"],
        quantized_algorithm=config["quantized_algorithm"],
        target_platform=config["target_platform"],
        num_npu_core=config["num_npu_core"],
        extra_qparams=None,
        dataset=str(args.dataset),
        hybrid_rate=config["hybrid_rate"],
        max_context=config["max_context"],
    )
    if ret != 0:
        raise SystemExit(f"RKLLM build failed with code {ret}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    ret = llm.export_rkllm(str(args.output))
    if ret != 0:
        raise SystemExit(f"RKLLM export failed with code {ret}")

    manifest = {
        "schema_version": 1,
        "source_model_id": config["source_model_id"],
        "source_model_revision": config["source_model_revision"],
        "build_config": config,
        "build_config_sha256": sha256(args.config),
        "calibration_sha256": sha256(args.dataset),
        "artifact": args.output.name,
        "artifact_sha256": sha256(args.output),
        "python": platform.python_version(),
        "packages": {
            "rkllm-toolkit": package_version("rkllm-toolkit"),
            "transformers": package_version("transformers"),
            "torch": package_version("torch"),
        },
        "hardware_validation": "not_run",
    }
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()


__all__ = ["PIN_SENTINEL", "load_build_config", "package_version", "sha256"]
