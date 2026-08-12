"""Build the portable Windows x64 Cloud Flowing internal-test bundle.

The builder never downloads resources. Every binary/model input is explicit,
verified against ``assets.lock.json``, and copied into a fresh output folder.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence


PACKAGE_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = PACKAGE_DIR.parents[1]
ASSET_LOCK_PATH = PACKAGE_DIR / "assets.lock.json"
REQUIREMENTS_LOCK_PATH = PACKAGE_DIR / "requirements.lock.txt"
TEMPLATES_DIR = PACKAGE_DIR / "templates"
RUNTIME_DIR = PACKAGE_DIR / "runtime"
SMOKE_DIR = PACKAGE_DIR / "smoke"
REQUIRED_VOICE_IDS = ("news-female1", "male1", "female1", "female2")
VOICE_FILENAMES = {
    "news-female1": "news-female.wav",
    "male1": "male1.wav",
    "female1": "female1.wav",
    "female2": "female2.wav",
}
VOICE_LABELS = {
    "news-female1": "新闻女声",
    "male1": "男声 1",
    "female1": "女声 1",
    "female2": "女声 2",
}
DEFAULT_VOICE_TEXT = {
    "news-female1": "各位村民，大家新年好。近期，湖北省武汉市等多个地区。",
    "male1": "这壶里装的可不是酒，而是药。",
    "female1": "小时候妈妈给我讲过一个在风暴中追求自由的探险家的故事。",
    "female2": "不加糖和奶的浓缩咖啡有着很好的提神效果。",
}
EXCLUDED_NAMES = {
    ".git",
    ".venv",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".reasonix",
    "__pycache__",
    "build",
    "dist",
    "logs",
    "tests",
    "work",
}
EXCLUDED_SUFFIXES = {".db", ".log", ".gguf", ".rkllm", ".pyc", ".pyo"}
SECRET_NAME_RE = re.compile(r"(^|[._-])(secret|token|password|credential|api[_-]?key)([._-]|$)", re.I)
WINDOWS_ABSOLUTE_RE = re.compile(r"(?i)(?<![a-z])(?:[a-z]:[\\/]|\\\\[^\\/]+[\\/])")


class BuildError(RuntimeError):
    """A deterministic, operator-actionable bundle build failure."""


@dataclass(frozen=True)
class FileRecord:
    path: str
    size: int
    sha256: str


def sha256_file(path: Path, *, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BuildError(f"Cannot read JSON {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise BuildError(f"{path.name} must contain a JSON object")
    return value


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def remove_tree_with_retry(path: Path, *, attempts: int = 12) -> None:
    """Remove one validated build tree despite short-lived Windows DLL locks."""

    last_error: OSError | None = None
    for attempt in range(attempts):
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except OSError as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(0.25)
    assert last_error is not None
    raise last_error


def resolve_source_commit(repository_root: Path, requested: str) -> str:
    if requested:
        candidate = requested.strip().lower()
    else:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository_root,
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.returncode:
            raise BuildError(f"Cannot resolve source commit: {completed.stderr.strip()}")
        candidate = completed.stdout.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", candidate):
        raise BuildError("--source-commit must be a complete 40-character Git object id")
    return candidate


def as_relative_bundle_path(value: str | Path) -> str:
    """Return one normalized bundle-relative path or reject traversal."""

    text = str(value).replace("\\", "/")
    if not text or WINDOWS_ABSOLUTE_RE.match(text) or text.startswith("/"):
        raise BuildError(f"Bundle path must be relative: {value}")
    normalized = PurePosixPath(text)
    if any(part in {"", ".", ".."} for part in normalized.parts):
        raise BuildError(f"Bundle path cannot contain traversal: {value}")
    return normalized.as_posix()


def verify_locked_file(path: Path, asset: Mapping[str, Any], description: str) -> str:
    if not path.is_file():
        raise BuildError(f"Missing {description}: {path}")
    expected = str(asset.get("sha256", "")).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise BuildError(f"assets.lock.json has no valid SHA256 for {description}")
    actual = sha256_file(path)
    if actual != expected:
        raise BuildError(f"{description} SHA256 mismatch: expected {expected}, got {actual}")
    return actual


def redistribution_decision(
    assets: Mapping[str, Mapping[str, Any]],
    asset_ids: Iterable[str],
    mode: str,
    assertions: Mapping[str, bool],
) -> tuple[bool, list[str]]:
    """Evaluate the immutable redistribution gate for selected assets."""

    reasons: list[str] = []
    for asset_id in asset_ids:
        if asset_id not in assets:
            raise BuildError(f"Unknown locked asset: {asset_id}")
        redistribution = assets[asset_id].get("redistribution", {})
        status = redistribution.get("status")
        reason = str(redistribution.get("reason", "No reason recorded"))
        if status == "allowed":
            continue
        if status == "conditional":
            assertion = str(redistribution.get("assertion", ""))
            if assertions.get(assertion) is True:
                continue
            reasons.append(f"{asset_id}: {reason} (missing assertion: {assertion})")
            continue
        if status == "blocked":
            reasons.append(f"{asset_id}: {reason}")
            continue
        reasons.append(f"{asset_id}: invalid redistribution status {status!r}")

    if mode == "distributable" and reasons:
        raise BuildError("Distributable build refused:\n- " + "\n- ".join(reasons))
    return not reasons, reasons


def should_copy_source(relative: Path) -> bool:
    if relative.parts and relative.parts[0] == "models":
        return False
    if any(part in EXCLUDED_NAMES for part in relative.parts):
        return False
    name = relative.name
    if name == ".env" or name.startswith(".env."):
        return False
    if SECRET_NAME_RE.search(name):
        return False
    if relative.suffix.lower() in EXCLUDED_SUFFIXES:
        return False
    if ".db-" in name.lower():
        return False
    return True


def copy_application(repository_root: Path, destination: Path) -> list[str]:
    """Copy the runtime application surface without local/build state."""

    copied: list[str] = []
    for top_level in ("agent_platform", "evaluation"):
        source_root = repository_root / top_level
        if not source_root.is_dir():
            raise BuildError(f"Application source directory is missing: {top_level}")
        for source in sorted(source_root.rglob("*")):
            relative = source.relative_to(repository_root)
            if source.is_dir() or not should_copy_source(relative):
                continue
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied.append(relative.as_posix())
    for filename in ("pyproject.toml", "README.md"):
        source = repository_root / filename
        if not source.is_file():
            raise BuildError(f"Application file is missing: {filename}")
        shutil.copy2(source, destination / filename)
        copied.append(filename)
    return copied


def copy_demo_data(repository_root: Path, bundle_root: Path) -> None:
    for name in ("demo_docs", "demo_files"):
        source = repository_root / name
        destination = bundle_root / name
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            destination.mkdir(parents=True, exist_ok=True)


def patch_embedded_python(python_root: Path) -> Path:
    candidates = sorted(python_root.glob("python3*._pth"))
    if len(candidates) != 1:
        raise BuildError(f"Expected one embedded Python _pth file, found {len(candidates)}")
    pth = candidates[0]
    zip_entries = [line.strip() for line in pth.read_text(encoding="utf-8").splitlines() if line.strip().endswith(".zip")]
    stdlib_zip = zip_entries[0] if zip_entries else "python312.zip"
    lines = [stdlib_zip, ".", "Lib\\site-packages", "..\\..\\app", "import site"]
    pth.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return pth


def read_requirements(path: Path) -> list[str]:
    requirements = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            requirements.append(stripped)
    if any(item.lower().split("==", 1)[0] == "av" for item in requirements):
        raise BuildError("PyAV must not be present in the offline runtime lock")
    return requirements


def ensure_wheelhouse(wheelhouse: Path, requirements: Sequence[str]) -> None:
    if not wheelhouse.is_dir():
        raise BuildError(f"Wheelhouse does not exist: {wheelhouse}")
    normalize_name = lambda value: re.sub(r"[-_.]+", "_", value).lower()
    wheel_names = {
        normalize_name(path.name.split("-", 1)[0]) for path in wheelhouse.glob("*.whl")
    }
    missing = []
    for requirement in requirements:
        name = normalize_name(requirement.split("==", 1)[0])
        if name not in wheel_names:
            missing.append(requirement)
    if missing:
        raise BuildError("Wheelhouse is incomplete: " + ", ".join(missing))
    if "av" in wheel_names:
        raise BuildError("Wheelhouse contains prohibited PyAV wheel; remove it before building")


def install_wheels(host_python: Path, wheelhouse: Path, requirements: Path, site_packages: Path) -> None:
    site_packages.mkdir(parents=True, exist_ok=True)
    command = [
        str(host_python),
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-index",
        "--find-links",
        str(wheelhouse),
        "--no-deps",
        "--no-compile",
        "--only-binary",
        ":all:",
        "--target",
        str(site_packages),
        "-r",
        str(requirements),
    ]
    completed = subprocess.run(command, text=True, capture_output=True, encoding="utf-8", errors="replace", check=False)
    if completed.returncode:
        raise BuildError(f"Offline wheel installation failed:\n{completed.stdout}\n{completed.stderr}")


def patch_faster_whisper_audio(site_packages: Path) -> Path:
    path = site_packages / "faster_whisper" / "audio.py"
    if not path.is_file():
        raise BuildError("Installed Faster-Whisper audio.py is missing")
    source = path.read_text(encoding="utf-8")
    if "import av\n" not in source:
        raise BuildError("Faster-Whisper 1.2.1 patch precondition failed: top-level import av not found")
    source = source.replace("import av\n", "", 1)
    replacements = {
        '    """Decodes the audio.': '    """Decodes the audio.',
        "    resampler = av.audio.resampler.AudioResampler(": "    import av\n\n    resampler = av.audio.resampler.AudioResampler(",
        "def _ignore_invalid_frames(frames):\n": "def _ignore_invalid_frames(frames):\n    import av\n\n",
        "def _group_frames(frames, num_samples=None):\n": "def _group_frames(frames, num_samples=None):\n    import av\n\n",
    }
    for needle, replacement in replacements.items():
        if needle not in source:
            raise BuildError(f"Faster-Whisper patch precondition failed: {needle!r}")
        source = source.replace(needle, replacement, 1)
    path.write_text(source, encoding="utf-8")
    return path


def validate_portable_python(python_exe: Path, app_root: Path) -> dict[str, str]:
    command = [
        str(python_exe),
        "-c",
        (
            "import importlib.util,numpy,agent_platform,faster_whisper,sherpa_onnx,sounddevice;"
            "from faster_whisper import WhisperModel;"
            "assert importlib.util.find_spec('av') is None;"
            "assert not hasattr(numpy.zeros(16000,dtype=numpy.float32),'read');"
            "print('portable-import-and-ndarray-entry-ok')"
        ),
    ]
    completed = subprocess.run(
        command,
        cwd=app_root,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env={**os.environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"},
    )
    if completed.returncode:
        raise BuildError(f"Portable Python validation failed:\n{completed.stdout}\n{completed.stderr}")
    return {"result": completed.stdout.strip(), "scope": "import-and-ndarray-entry-only-not-real-transcription"}


def copy_tree_filtered(
    source: Path,
    destination: Path,
    *,
    ignored_names: Sequence[str] = (),
) -> None:
    if not source.is_dir():
        raise BuildError(f"Required directory does not exist: {source}")
    ignore_patterns = ("__pycache__", "*.pyc", ".pytest_cache", *ignored_names)
    shutil.copytree(
        source,
        destination,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(*ignore_patterns),
    )


def read_voice_manifest(source: Path) -> dict[str, Any]:
    manifest_path = source / "voices-local-validation.json"
    if manifest_path.is_file():
        manifest = load_json(manifest_path)
        entries = manifest.get("voices")
        if not isinstance(entries, list):
            raise BuildError("voices-local-validation.json must contain a voices array")
        return manifest
    prompt_path = source / "prompt.txt"
    prompt_text: dict[str, str] = {}
    if prompt_path.is_file():
        for line in prompt_path.read_text(encoding="utf-8", errors="replace").splitlines():
            filename, separator, text = line.partition(" ")
            if separator and text.strip():
                prompt_text[filename.strip()] = text.strip()
    voices = []
    for voice_id, filename in VOICE_FILENAMES.items():
        voices.append(
            {
                "id": voice_id,
                "label": VOICE_LABELS[voice_id],
                "filename": filename,
                "reference_text": prompt_text.get(filename, DEFAULT_VOICE_TEXT[voice_id]),
            }
        )
    return {"schema_version": 1, "default_voice_id": "news-female1", "voices": voices}


def stage_local_voices(source: Path, bundle_root: Path) -> list[dict[str, Any]]:
    manifest = read_voice_manifest(source)
    configured = {str(entry.get("id")): entry for entry in manifest.get("voices", []) if isinstance(entry, dict)}
    if set(configured) != set(REQUIRED_VOICE_IDS):
        raise BuildError("Local voice source must configure exactly news-female1, male1, female1, female2")
    destination = bundle_root / "models" / "zipvoice" / "voices"
    destination.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []
    for voice_id in REQUIRED_VOICE_IDS:
        entry = configured[voice_id]
        filename = str(entry.get("filename") or entry.get("wav") or entry.get("reference_audio_path") or "")
        if not filename or Path(filename).is_absolute() or ".." in Path(filename).parts:
            raise BuildError(f"Invalid local voice path for {voice_id}")
        source_path = (source / filename).resolve()
        try:
            source_path.relative_to(source.resolve())
        except ValueError as exc:
            raise BuildError(f"Local voice path leaves source directory: {voice_id}") from exc
        if not source_path.is_file():
            raise BuildError(f"Missing local voice WAV for {voice_id}: {filename}")
        text = str(entry.get("reference_text") or entry.get("transcript") or "").strip()
        if not text:
            raise BuildError(f"Local voice transcript is missing: {voice_id}")
        target = destination / f"{voice_id}.wav"
        shutil.copy2(source_path, target)
        entries.append(
            {
                "id": voice_id,
                "label": str(entry.get("label") or VOICE_LABELS[voice_id]),
                "reference_audio_path": f"models/zipvoice/voices/{voice_id}.wav",
                "reference_text": text,
                "sha256": sha256_file(target),
            }
        )
    return entries


def bundle_configuration() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "app_root": "app",
        "runtime": {
            "python": "runtime/python/python.exe",
            "llama_server": "runtime/llama.cpp/llama-server.exe",
        },
        "agent": {"host": "127.0.0.1", "port": 8000},
        "llamacpp": {"host": "127.0.0.1", "port": 8080, "start_timeout_seconds": 600},
        "paths": {
            "database": "data/agent_platform.db",
            "audit": "logs/audit",
            "tts_output": "data/tts",
            "meeting_output": "data/meeting_notes",
            "authorized_files": ["data/authorized_files", "demo_files"],
            "knowledge": ["data/knowledge", "demo_docs"],
            "whisper_model": "models/faster-whisper-small",
        },
        "tts": {"provider": "zipvoice", "num_threads": 4, "speed": 1.0, "num_steps": 4},
        "voice": {"enabled": True, "cpu_threads": 8, "num_workers": 1, "beam_size": 3, "vad_enabled": True},
    }


def models_configuration() -> dict[str, Any]:
    acknowledgement = (
        "Read THIRD_PARTY_LICENSES.md and the upstream model license. "
        "Acceptance permits only use allowed by that license and does not grant redistribution rights."
    )
    return {
        "schema_version": 1,
        "default_model": "qwen",
        "models": [
            {
                "id": "qwen",
                "display_name": "Qwen2.5 3B Instruct Q4_K_M",
                "model_name": "qwen2.5-3b-instruct",
                "path": "models/qwen2.5-3b-instruct-q4_k_m.gguf",
                "sha256": "626b4a6678b86442240e33df819e00132d3ba7dddfe1cdc4fbb18e0a9615c62d",
                "threads": 4,
                "context_size": 4096,
                "max_tokens": 512,
                "batch_size": 256,
                "parallel": 1,
                "license_acknowledged": False,
                "required_acknowledgement": acknowledgement,
            },
            {
                "id": "lfm",
                "display_name": "LFM2.5 1.2B Instruct Q4_K_M",
                "model_name": "lfm2.5-1.2b-instruct",
                "path": "models/LFM2.5-1.2B-Instruct-Q4_K_M.gguf",
                "sha256": "b1b3de114215d9507409a662a501a631095a479a419584e8a2ded6304b19b4f5",
                "threads": 4,
                "context_size": 4096,
                "max_tokens": 512,
                "batch_size": 256,
                "parallel": 1,
                "license_acknowledged": False,
                "required_acknowledgement": acknowledgement,
            },
        ],
    }


def package_status(mode: str, reasons: Sequence[str]) -> dict[str, Any]:
    redistributable = mode == "distributable" and not reasons
    return {
        "schema_version": 1,
        "status": "REDISTRIBUTABLE" if redistributable else "NON_DISTRIBUTABLE_LOCAL_VALIDATION",
        "build_mode": mode,
        "redistributable": redistributable,
        "reasons": list(reasons),
        "generated_at": datetime.now(UTC).isoformat(),
    }


def iter_manifest_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name not in {"MANIFEST.json", "SHA256SUMS"}:
            yield path


def manifest_records(root: Path) -> list[FileRecord]:
    return [
        FileRecord(path=path.relative_to(root).as_posix(), size=path.stat().st_size, sha256=sha256_file(path))
        for path in iter_manifest_files(root)
    ]


def scan_metadata_for_private_paths(root: Path) -> None:
    candidates = [
        *root.glob("*.md"),
        *root.glob("*.json"),
        *root.glob("*.txt"),
        *root.glob("*.env"),
        *(root / "config").glob("*.json"),
    ]
    for path in candidates:
        text = path.read_text(encoding="utf-8", errors="replace")
        if WINDOWS_ABSOLUTE_RE.search(text) or "C:\\Users\\" in text:
            raise BuildError(f"Generated metadata contains a local absolute path: {path.relative_to(root)}")
        if re.search(r"(?im)^\s*(?:MODEL_)?API_KEY\s*=\s*\S+", text):
            raise BuildError(f"Generated metadata contains an API key value: {path.relative_to(root)}")


def write_manifests(bundle_root: Path, metadata: dict[str, Any]) -> None:
    records = manifest_records(bundle_root)
    total_size = sum(record.size for record in records)
    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "total_file_count": len(records),
        "total_size_bytes": total_size,
        "files": [record.__dict__ for record in records],
    }
    write_json(bundle_root / "MANIFEST.json", manifest)
    mutable_paths = {
        "config/active-model.txt",
        "config/license-acceptance.json",
        "config/voices.json",
    }
    sums = "".join(
        f"{record.sha256}  {record.path}\n" for record in records if record.path not in mutable_paths
    )
    (bundle_root / "SHA256SUMS").write_text(sums, encoding="utf-8")
    metadata["payload_file_count"] = len(records)
    metadata["payload_size_bytes"] = total_size
    write_json(bundle_root / "BUILD-METADATA.json", metadata)
    # Include BUILD-METADATA itself in the final checksums without creating a
    # self-referential MANIFEST record.
    build_metadata = bundle_root / "BUILD-METADATA.json"
    with (bundle_root / "SHA256SUMS").open("a", encoding="utf-8") as stream:
        stream.write(f"{sha256_file(build_metadata)}  BUILD-METADATA.json\n")


def create_archive(bundle_root: Path, archive_path: Path) -> None:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path, "w", allowZip64=True) as archive:
        for path in sorted(bundle_root.rglob("*")):
            if path.is_file():
                arcname = PurePosixPath(bundle_root.name) / PurePosixPath(path.relative_to(bundle_root).as_posix())
                compression = zipfile.ZIP_STORED if path.suffix.lower() in {".gguf", ".onnx", ".bin", ".zip"} else zipfile.ZIP_DEFLATED
                archive.write(path, arcname.as_posix(), compress_type=compression)


def build(args: argparse.Namespace) -> Path:
    repository_root = args.repository_root.resolve()
    source_commit = resolve_source_commit(repository_root, args.source_commit)
    lock = load_json(args.assets_lock)
    assets = lock.get("assets")
    if not isinstance(assets, dict):
        raise BuildError("assets.lock.json must contain an assets object")
    assertions = load_json(args.rights_assertions).get("assertions", {}) if args.rights_assertions else {}
    if not isinstance(assertions, dict):
        raise BuildError("rights assertion file must contain an assertions object")
    selected_assets = (
        "python",
        "llamacpp",
        "qwen",
        "lfm",
        "faster_whisper_small",
        "zipvoice",
        "zipvoice_vocoder",
        "voice_references",
    )
    _, reasons = redistribution_decision(assets, selected_assets, args.mode, assertions)
    if args.mode == "distributable" and args.local_voice_smoke_source:
        raise BuildError("--local-voice-smoke-source is forbidden in distributable mode")

    inputs = {
        "python": args.python_archive,
        "llamacpp": args.llama_archive,
        "qwen": args.qwen_model,
        "lfm": args.lfm_model,
        "faster_whisper_small": args.whisper_model / str(assets["faster_whisper_small"]["required_file"]),
        "zipvoice": args.zipvoice_model / str(assets["zipvoice"]["required_file"]),
        "zipvoice_vocoder": args.zipvoice_vocoder,
    }
    input_hashes = {asset_id: verify_locked_file(path, assets[asset_id], asset_id) for asset_id, path in inputs.items()}
    requirements = read_requirements(args.requirements_lock)
    ensure_wheelhouse(args.wheelhouse, requirements)

    output_root = args.output.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    bundle_root = output_root / args.bundle_name
    if bundle_root.exists():
        if not args.replace:
            raise BuildError(f"Output already exists; pass --replace to replace it: {bundle_root}")
        if bundle_root.parent != output_root:
            raise BuildError("Refusing to remove an output outside the selected directory")
        remove_tree_with_retry(bundle_root)

    stage_root = Path(tempfile.mkdtemp(prefix=f".{args.bundle_name}-", dir=output_root))
    try:
        (stage_root / "app").mkdir(parents=True)
        copy_application(repository_root, stage_root / "app")
        copy_demo_data(repository_root, stage_root)
        for name in ("data/authorized_files", "data/knowledge", "data/meeting_notes", "data/tts", "logs/audit", "run"):
            (stage_root / name).mkdir(parents=True, exist_ok=True)

        python_root = stage_root / "runtime" / "python"
        llama_root = stage_root / "runtime" / "llama.cpp"
        python_root.mkdir(parents=True)
        llama_root.mkdir(parents=True)
        with zipfile.ZipFile(args.python_archive) as archive:
            archive.extractall(python_root)
        with zipfile.ZipFile(args.llama_archive) as archive:
            archive.extractall(llama_root)
        patch_embedded_python(python_root)
        site_packages = python_root / "Lib" / "site-packages"
        install_wheels(args.host_python, args.wheelhouse, args.requirements_lock, site_packages)
        patch_path = patch_faster_whisper_audio(site_packages)

        copy_tree_filtered(args.whisper_model, stage_root / "models" / "faster-whisper-small")
        # Reference recordings are separate rights-managed inputs.  The model's
        # example directory also contains the removed Lei Jun sample, so never
        # copy it as part of the ZipVoice runtime assets.
        copy_tree_filtered(
            args.zipvoice_model,
            stage_root / "models" / "zipvoice" / args.zipvoice_model.name,
            ignored_names=("test_wavs",),
        )
        zipvoice_relative = f"models/zipvoice/{args.zipvoice_model.name}"
        vocoder_target = stage_root / "models" / "zipvoice" / "vocos_24khz.onnx"
        vocoder_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(args.zipvoice_vocoder, vocoder_target)
        models_root = stage_root / "models"
        shutil.copy2(args.qwen_model, models_root / "qwen2.5-3b-instruct-q4_k_m.gguf")
        shutil.copy2(args.lfm_model, models_root / "LFM2.5-1.2B-Instruct-Q4_K_M.gguf")

        if RUNTIME_DIR.is_dir():
            for path in RUNTIME_DIR.iterdir():
                target = stage_root / path.name
                if path.is_dir():
                    copy_tree_filtered(path, target)
                else:
                    shutil.copy2(path, target)
        if SMOKE_DIR.is_dir():
            copy_tree_filtered(SMOKE_DIR, stage_root / "scripts" / "smoke")

        config_root = stage_root / "config"
        write_json(config_root / "bundle.json", bundle_configuration())
        write_json(config_root / "models.json", models_configuration())
        write_json(config_root / "license-acceptance.json", {"schema_version": 1, "models": {"qwen": False, "lfm": False}})
        (config_root / "active-model.txt").write_text("qwen\n", encoding="utf-8")

        voice_entries: list[dict[str, Any]] = []
        local_voice_validation = bool(args.local_voice_smoke_source)
        if args.local_voice_smoke_source:
            voice_entries = stage_local_voices(args.local_voice_smoke_source, stage_root)
        voices = {
            "schema_version": 1,
            "redistribution_authorized": False,
            "local_validation_authorized_by_operator": local_voice_validation,
            "package_status_required": "NON_DISTRIBUTABLE_LOCAL_VALIDATION" if local_voice_validation else None,
            "model_dir": zipvoice_relative,
            "vocoder_path": "models/zipvoice/vocos_24khz.onnx",
            "default_voice_id": "news-female1",
            "voices": voice_entries,
        }
        write_json(config_root / "voices.json", voices)
        shutil.copy2(args.assets_lock, config_root / "assets.lock.json")
        shutil.copy2(args.requirements_lock, config_root / "requirements.lock.txt")

        status_reasons = reasons or ["No redistribution blockers recorded by assets.lock.json"]
        status = package_status(args.mode, status_reasons if args.mode == "local-validation" else [])
        write_json(stage_root / "PACKAGE-STATUS.json", status)
        status_template = (TEMPLATES_DIR / "PACKAGE-STATUS.md").read_text(encoding="utf-8")
        status_text = (
            status_template.replace("{{BUILD_MODE}}", args.mode)
            .replace("{{REDISTRIBUTABLE}}", "YES" if status["redistributable"] else "NO")
            .replace(
                "{{STATUS_MESSAGE}}",
                "DO NOT DISTRIBUTE OR UPLOAD THIS LOCAL VALIDATION PACKAGE.\n\n"
                + "\n".join(f"- {reason}" for reason in status["reasons"])
                if not status["redistributable"]
                else "All selected assets passed the recorded redistribution gate.",
            )
        )
        (stage_root / "PACKAGE-STATUS.md").write_text(status_text, encoding="utf-8")
        for template_name in ("INSTALL.md", "THIRD_PARTY_LICENSES.md", "PATCHES.md"):
            shutil.copy2(TEMPLATES_DIR / template_name, stage_root / template_name)

        portable_validation = validate_portable_python(python_root / "python.exe", stage_root / "app")
        metadata = {
            "schema_version": 1,
            "generated_at": datetime.now(UTC).isoformat(),
            "source_commit": source_commit,
            "build_mode": args.mode,
            "package_status": status["status"],
            "input_hashes": input_hashes,
            "runtime": {"python": "3.12.10", "llamacpp": "b10375"},
            "patches": [
                {
                    "component": "faster-whisper",
                    "version": "1.2.1",
                    "path": patch_path.relative_to(stage_root).as_posix(),
                    "sha256": sha256_file(patch_path),
                    "description": "Lazy PyAV imports for the in-memory NumPy-only Agent path; PyAV excluded.",
                }
            ],
            "portable_validation": portable_validation,
            "not_validated_by_builder": ["real model inference", "real Faster-Whisper inference", "ZipVoice synthesis"],
        }
        scan_metadata_for_private_paths(stage_root)
        write_manifests(stage_root, metadata)
        scan_metadata_for_private_paths(stage_root)
        stage_root.rename(bundle_root)
    except Exception as build_error:
        if stage_root.exists():
            try:
                remove_tree_with_retry(stage_root)
            except OSError as cleanup_error:
                build_error.add_note(f"Temporary build cleanup also failed: {cleanup_error}")
        raise

    if args.archive:
        create_archive(bundle_root, output_root / f"{args.bundle_name}.zip")
    return bundle_root


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("local-validation", "distributable"), default="local-validation")
    parser.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--source-commit", default="", help="Full Git object id; defaults to repository HEAD")
    parser.add_argument("--qwen-model", type=Path, required=True)
    parser.add_argument("--lfm-model", type=Path, required=True)
    parser.add_argument("--whisper-model", type=Path, required=True, help="Faster-Whisper small directory")
    parser.add_argument("--zipvoice-model", type=Path, required=True, help="ZipVoice model directory")
    parser.add_argument("--zipvoice-vocoder", type=Path, required=True)
    parser.add_argument("--python-archive", type=Path, required=True, help="Cached CPython embeddable ZIP")
    parser.add_argument("--llama-archive", type=Path, required=True, help="Cached llama.cpp Windows CPU ZIP")
    parser.add_argument("--wheelhouse", type=Path, required=True, help="Pre-downloaded win_amd64 CPython 3.12 wheels")
    parser.add_argument("--local-voice-smoke-source", type=Path, help="Local-only four-WAV source; forbidden for distribution")
    parser.add_argument("--rights-assertions", type=Path, help="Company-written JSON assertions for conditional assets")
    parser.add_argument("--assets-lock", type=Path, default=ASSET_LOCK_PATH)
    parser.add_argument("--requirements-lock", type=Path, default=REQUIREMENTS_LOCK_PATH)
    parser.add_argument("--host-python", type=Path, default=Path(sys.executable))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bundle-name", default="cloud-flowing-windows-x64-offline")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--archive", action="store_true", help="Also create a Zip64 archive (large, potentially slow)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        bundle_root = build(args)
    except BuildError as exc:
        parser.exit(2, f"build refused: {exc}\n")
    print(json.dumps({"bundle": str(bundle_root), "mode": args.mode}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
