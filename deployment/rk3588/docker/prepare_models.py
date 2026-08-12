"""Download the two pinned GGUF files and verify their immutable SHA256."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen


def download(name: str, spec: dict[str, object], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = str(spec["filename"])
    destination = output_dir / filename
    expected = str(spec["sha256"])
    if destination.is_file() and sha256(destination) == expected:
        print(f"{name}: already verified: {destination}")
        return destination
    temporary = destination.with_suffix(destination.suffix + ".part")
    url = (
        f"https://huggingface.co/{spec['repository']}/resolve/{spec['revision']}/"
        f"{filename}?download=true"
    )
    request = Request(url, headers={"User-Agent": "cloud-flowing-rk3588-poc/1"})
    digest = hashlib.sha256()
    received = 0
    try:
        with urlopen(request, timeout=120) as response, temporary.open("wb") as handle:
            while chunk := response.read(8 * 1024 * 1024):
                handle.write(chunk)
                digest.update(chunk)
                received += len(chunk)
                print(f"{name}: {received / 1024 / 1024:.1f} MiB", end="\r", flush=True)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    actual = digest.hexdigest()
    if actual != expected:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"{name}: SHA256 mismatch: expected {expected}, got {actual}")
    os.replace(temporary, destination)
    print(f"{name}: verified {actual}: {destination}")
    return destination


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=("qwen", "lfm", "all"), default="all")
    parser.add_argument("--output", type=Path, default=Path("models"))
    args = parser.parse_args()
    lock_path = Path(__file__).with_name("models.lock.json")
    models = json.loads(lock_path.read_text(encoding="utf-8"))
    names = tuple(models) if args.model == "all" else (args.model,)
    for name in names:
        download(name, models[name], args.output)


if __name__ == "__main__":
    main()
