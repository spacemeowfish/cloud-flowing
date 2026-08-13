"""Safely extract ZipVoice runtime files without bundled example voices."""

from __future__ import annotations

import argparse
import shutil
import tarfile
from pathlib import Path, PurePosixPath


class ExtractionError(RuntimeError):
    """Raised when an archive member would escape or alter the output tree."""


def extract_zipvoice(archive_path: Path, output_root: Path) -> list[Path]:
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []
    with tarfile.open(archive_path, "r:bz2") as archive:
        for member in archive.getmembers():
            relative = PurePosixPath(member.name)
            if relative.is_absolute() or ".." in relative.parts:
                raise ExtractionError(f"unsafe archive path: {member.name}")
            if "test_wavs" in relative.parts:
                continue
            if member.issym() or member.islnk() or member.isdev():
                raise ExtractionError(f"unsupported archive member: {member.name}")
            destination = output_root.joinpath(*relative.parts)
            try:
                destination.resolve().relative_to(output_root)
            except ValueError as exc:
                raise ExtractionError(f"archive path leaves output root: {member.name}") from exc
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                continue
            source = archive.extractfile(member)
            if source is None:
                raise ExtractionError(f"archive member cannot be read: {member.name}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with source, destination.open("wb") as target:
                shutil.copyfileobj(source, target)
            extracted.append(destination)
    return extracted


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    extracted = extract_zipvoice(args.archive, args.output)
    print(f"Extracted {len(extracted)} ZipVoice runtime files; skipped bundled test_wavs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
