import io
import shutil
import subprocess
import tarfile
import textwrap
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


def test_python_launcher_without_runtime_falls_back_to_winget(tmp_path: Path) -> None:
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if powershell is None:
        pytest.skip("PowerShell is required for the Windows setup regression test")

    harness = tmp_path / "python-fallback-regression.ps1"
    harness.write_text(
        textwrap.dedent(
            r'''
            param([Parameter(Mandatory = $true)][string]$SetupScript)

            $ErrorActionPreference = "Stop"
            $PlanOnly = $false
            $RepositoryRoot = $PSScriptRoot
            $PythonPath = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
            $env:LOCALAPPDATA = $PSScriptRoot
            $script:PythonInstalled = $false
            $script:VenvCreated = $false

            $tokens = $null
            $parseErrors = $null
            $ast = [System.Management.Automation.Language.Parser]::ParseFile(
                $SetupScript,
                [ref]$tokens,
                [ref]$parseErrors
            )
            if ($parseErrors.Count -ne 0) {
                throw "Setup script failed to parse."
            }
            foreach ($name in @(
                "Write-Step",
                "Invoke-External",
                "Resolve-Python312Launcher",
                "Enable-WinGetWinINetDownloader",
                "Install-PythonIfMissing"
            )) {
                $definition = $ast.Find({
                    param($node)
                    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
                        $node.Name -eq $name
                }, $true)
                if (-not $definition) {
                    throw "Setup function was not found: $name"
                }
                . ([scriptblock]::Create($definition.Extent.Text))
            }

            function global:Get-Command {
                [CmdletBinding()]
                param([Parameter(Mandatory = $true, Position = 0)][string]$Name)

                switch -Exact ($Name) {
                    "py" { return [pscustomobject]@{ Source = "py.exe" } }
                    "winget" { return [pscustomobject]@{ Source = "winget.exe" } }
                    default { return $null }
                }
            }

            function global:py.exe {
                param(
                    [Parameter(ValueFromRemainingArguments = $true)]
                    [string[]]$PassedArguments
                )

                if (-not $script:PythonInstalled) {
                    Write-Error "No suitable Python runtime found"
                }
                if ($PassedArguments -contains "-c") {
                    Write-Output "3.12"
                } else {
                    $script:VenvCreated = $true
                }
                $global:LASTEXITCODE = 0
            }

            function global:winget.exe {
                param(
                    [Parameter(ValueFromRemainingArguments = $true)]
                    [string[]]$PassedArguments
                )

                $script:PythonInstalled = $true
                $global:LASTEXITCODE = 0
            }

            Install-PythonIfMissing
            if (-not $script:PythonInstalled) {
                throw "winget fallback was not called."
            }
            if (-not $script:VenvCreated) {
                throw "Python 3.12 virtual environment was not created after fallback."
            }
            '''
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(harness),
            "-SetupScript",
            str(SCRIPT),
        ],
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_colleague_guide_covers_fork_models_testing_and_pr() -> None:
    content = GUIDE.read_text(encoding="utf-8")

    for required in (
        "Fork",
        "Setup-PC-Test.ps1",
        "py.exe",
        "默认保持禁用",
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


def _function_body(content: str, name: str) -> str:
    """Return the text of a PowerShell function body between its outer braces."""
    start = content.index(f"function {name} {{") + len(f"function {name} {{")
    depth = 1
    index = start
    while index < len(content) and depth:
        if content[index] == "{":
            depth += 1
        elif content[index] == "}":
            depth -= 1
        index += 1
    return content[start:index - 1]


def test_setup_script_forces_winget_wininet_downloader() -> None:
    content = SCRIPT.read_text(encoding="utf-8")

    assert "function Enable-WinGetWinINetDownloader" in content
    assert "Microsoft.DesktopAppInstaller_8wekyb3d8bbwe" in content
    assert '"downloader"' in content or "downloader =" in content
    assert "wininet" in content

    # The WinINet switch must run before the winget install in both paths that
    # use winget (Python 3.12 and Ollama), so the DeliveryOptimization downloader
    # cannot stall GitHub downloads first.
    for name in ("Install-PythonIfMissing", "Install-OllamaIfMissing"):
        body = _function_body(content, name)
        assert "Enable-WinGetWinINetDownloader" in body
        assert body.index("Enable-WinGetWinINetDownloader") < body.index(
            "Invoke-External $winget.Source"
        )


def test_ollama_winget_install_forces_wininet_downloader(tmp_path: Path) -> None:
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if powershell is None:
        pytest.skip("PowerShell is required for the Windows setup regression test")

    harness = tmp_path / "ollama-wininet-regression.ps1"
    harness.write_text(
        textwrap.dedent(
            r'''
            param([Parameter(Mandatory = $true)][string]$SetupScript)

            $ErrorActionPreference = "Stop"
            $PlanOnly = $false
            $env:LOCALAPPDATA = $PSScriptRoot
            $script:WingetCalled = $false
            $script:OllamaResolved = $false

            $tokens = $null
            $parseErrors = $null
            $ast = [System.Management.Automation.Language.Parser]::ParseFile(
                $SetupScript,
                [ref]$tokens,
                [ref]$parseErrors
            )
            if ($parseErrors.Count -ne 0) {
                throw "Setup script failed to parse."
            }
            foreach ($name in @(
                "Write-Step",
                "Invoke-External",
                "Enable-WinGetWinINetDownloader",
                "Install-OllamaIfMissing"
            )) {
                $definition = $ast.Find({
                    param($node)
                    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
                        $node.Name -eq $name
                }, $true)
                if (-not $definition) {
                    throw "Setup function was not found: $name"
                }
                . ([scriptblock]::Create($definition.Extent.Text))
            }

            function global:Get-Command {
                [CmdletBinding()]
                param([Parameter(Mandatory = $true, Position = 0)][string]$Name)

                switch -Exact ($Name) {
                    "winget" { return [pscustomobject]@{ Source = "winget.exe" } }
                    default { return $null }
                }
            }

            function global:winget.exe {
                param(
                    [Parameter(ValueFromRemainingArguments = $true)]
                    [string[]]$PassedArguments
                )

                $script:WingetCalled = $true
                $global:LASTEXITCODE = 0
            }

            function global:Resolve-Ollama {
                if ($script:OllamaResolved) {
                    return "ollama.exe"
                }
                $script:OllamaResolved = $true
                return $null
            }

            Install-OllamaIfMissing | Out-Null
            if (-not $script:WingetCalled) {
                throw "winget install was not called for Ollama."
            }
            $settingsPath = Join-Path $env:LOCALAPPDATA "Packages\Microsoft.DesktopAppInstaller_8wekyb3d8bbwe\LocalState\settings.json"
            if (-not (Test-Path -LiteralPath $settingsPath -PathType Leaf)) {
                throw "WinINet settings.json was not written before the Ollama winget install."
            }
            $settings = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
            if ($settings.network.downloader -ne "wininet") {
                throw "network.downloader was not set to wininet."
            }
            '''
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(harness),
            "-SetupScript",
            str(SCRIPT),
        ],
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_colleague_guide_mentions_winget_wininet_downloader() -> None:
    content = GUIDE.read_text(encoding="utf-8")

    assert "wininet" in content
    assert "DeliveryOptimization" in content
    assert "Microsoft.DesktopAppInstaller_8wekyb3d8bbwe" in content
