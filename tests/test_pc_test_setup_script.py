import io
import tarfile
from pathlib import Path

import pytest

from scripts.extract_zipvoice import ExtractionError, extract_zipvoice


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "Setup-PC-Test.ps1"
GUIDE = ROOT / "docs" / "testing" / "COLLEAGUE-PC-SETUP.md"


def test_pc_setup_script_keeps_downloads_out_of_git_and_pins_assets() -> None:
    content = SCRIPT.read_text(encoding="utf-8")

    assert 'Join-Path $RepositoryRoot ".local-models"' in content
    assert "qwen2.5:3b" in content
    assert "lfm2.5-thinking:1.2b" in content
    assert "536b0662742c02347bc0e980a01041f333bce120" in content
    assert "3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671" in content
    assert "77219c8b40f4ee8d73a7f902305ff6c1128ef9b54461c41b4ca6ed890b6c2803" in content
    assert "3cc2e08a96610d7ea1b227398e97cdbbe0414499741d3aec0b8113db2a2ab251" in content
    assert "bcb3b970e384161c4d634f0bb9e999ff1c471b34c9bc0b1049a5014065ed3cc0" in content
    assert "I ACCEPT" in content
    assert 'TTS_PROVIDER"] = "disabled"' in content
    assert "ZIPVOICE_VOICES" not in content
    assert "extract_zipvoice.py" in content
    assert 'Remove-Item -LiteralPath $archive' in content
    assert 'Join-Path $ZipVoiceModelRoot "encoder.int8.onnx"' in content
    assert 'Join-Path $ZipVoiceModelRoot "espeak-ng-data"' in content


def test_colleague_guide_covers_fork_models_testing_and_pr() -> None:
    content = GUIDE.read_text(encoding="utf-8")

    for required in (
        "Fork",
        "Setup-PC-Test.ps1",
        "qwen2.5:3b",
        "lfm2.5-thinking:1.2b",
        "Faster-Whisper",
        "ZipVoice",
        "逐字匹配",
        "upstream/main",
        ".ai-team/TASK.md",
        "Pull Request",
    ):
        assert required in content


def test_local_model_directory_is_ignored() -> None:
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".local-models/" in ignored


def _write_archive(path: Path, members: dict[str, bytes]) -> None:
    with tarfile.open(path, "w:bz2") as archive:
        for name, payload in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))


def test_zipvoice_extractor_skips_upstream_example_voices(tmp_path: Path) -> None:
    archive = tmp_path / "zipvoice.tar.bz2"
    output = tmp_path / "models"
    _write_archive(
        archive,
        {
            "zipvoice/decoder.int8.onnx": b"model",
            "zipvoice/test_wavs/leijun-1.wav": b"voice",
            "zipvoice/test_wavs/prompt.txt": b"transcript",
        },
    )

    extracted = extract_zipvoice(archive, output)

    assert extracted == [output / "zipvoice" / "decoder.int8.onnx"]
    assert not (output / "zipvoice" / "test_wavs").exists()


def test_zipvoice_extractor_rejects_parent_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.tar.bz2"
    _write_archive(archive, {"../escape.txt": b"no"})

    with pytest.raises(ExtractionError, match="unsafe archive path"):
        extract_zipvoice(archive, tmp_path / "models")
