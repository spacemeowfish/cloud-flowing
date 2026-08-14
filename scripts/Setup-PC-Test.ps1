[CmdletBinding()]
param(
    [switch]$IncludeZipVoice,
    [switch]$PlanOnly,
    [switch]$AcceptModelLicenses
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$ModelRoot = Join-Path $RepositoryRoot ".local-models"
$WhisperRoot = Join-Path $ModelRoot "faster-whisper-small"
$ZipVoiceRoot = Join-Path $ModelRoot "zipvoice"
$ZipVoiceModelRoot = Join-Path $ZipVoiceRoot "sherpa-onnx-zipvoice-distill-int8-zh-en-emilia"
$VocoderPath = Join-Path $ZipVoiceRoot "vocos_24khz.onnx"
$PythonPath = Join-Path $RepositoryRoot ".venv\Scripts\python.exe"
$EnvPath = Join-Path $RepositoryRoot ".env"
$QwenModel = "qwen2.5:3b"
$LfmModel = "lfm2.5-thinking:1.2b"

$WhisperFiles = @(
    @{ Name = "config.json"; Sha256 = "b55496ac7940a7ae47d2c01eab40edfd8701feec1229d9cce3b40014383fb828" },
    @{ Name = "model.bin"; Sha256 = "3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671" },
    @{ Name = "tokenizer.json"; Sha256 = "fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab" },
    @{ Name = "vocabulary.txt"; Sha256 = "34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913" }
)

$ZipVoiceArchiveUrl = "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/sherpa-onnx-zipvoice-distill-int8-zh-en-emilia.tar.bz2"
$ZipVoiceArchiveSha256 = "77219c8b40f4ee8d73a7f902305ff6c1128ef9b54461c41b4ca6ed890b6c2803"
$VocoderUrl = "https://github.com/k2-fsa/sherpa-onnx/releases/download/vocoder-models/vocos_24khz.onnx"
$VocoderSha256 = "bcb3b970e384161c4d634f0bb9e999ff1c471b34c9bc0b1049a5014065ed3cc0"

function Write-Step([string]$Message) {
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Invoke-External {
    param([string]$Command, [string[]]$Arguments)
    if ($PlanOnly) {
        Write-Host ("PLAN: {0} {1}" -f $Command, ($Arguments -join " "))
        return
    }
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed ($LASTEXITCODE): $Command $($Arguments -join ' ')"
    }
}

function Confirm-ModelLicenses {
    Write-Host "Qwen 2.5 3B model and license: https://ollama.com/library/qwen2.5:3b"
    Write-Host "LFM model and license: https://ollama.com/library/lfm2.5-thinking:1.2b"
    Write-Warning "Downloading a model does not grant rights beyond its license. Qwen 2.5 3B uses the Qwen Research License; LFM commercial eligibility depends on its license conditions."
    if ($PlanOnly -or $AcceptModelLicenses) {
        return
    }
    $answer = Read-Host "After reading both licenses, enter I ACCEPT to continue"
    if ($answer -cne "I ACCEPT") {
        throw "Model license acknowledgement was not provided. No model was downloaded."
    }
}

function Resolve-Python312Launcher {
    $knownPython = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
    foreach ($candidate in @("py", $knownPython, "python")) {
        $command = Get-Command $candidate -ErrorAction SilentlyContinue
        if (-not $command) { continue }
        $prefix = @()
        if ((Split-Path -Leaf $command.Source) -eq "py.exe") {
            $prefix = @("-3.12")
        }
        if ($PlanOnly) {
            return @{ Path = $command.Source; Prefix = $prefix }
        }
        try {
            $version = & $command.Source @prefix -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        } catch {
            continue
        }
        if ($LASTEXITCODE -eq 0 -and $version -eq "3.12") {
            return @{ Path = $command.Source; Prefix = $prefix }
        }
    }
    return $null
}

function Enable-WinGetWinINetDownloader {
    # winget's default DeliveryOptimization downloader can stall near 100% and
    # write zero-filled files for GitHub-hosted packages behind a proxy (observed
    # four times on a Windows 11 machine). Force the WinINet downloader so
    # `winget install` completes reliably.
    $packageRoot = Join-Path $env:LOCALAPPDATA "Packages\Microsoft.DesktopAppInstaller_8wekyb3d8bbwe\LocalState"
    $settingsPath = Join-Path $packageRoot "settings.json"
    $settingsJson = @{ network = @{ downloader = "wininet" } } | ConvertTo-Json -Depth 3
    if ($PlanOnly) {
        Write-Host "PLAN: write $settingsPath -> $settingsJson"
        return
    }
    New-Item -ItemType Directory -Path $packageRoot -Force | Out-Null
    [System.IO.File]::WriteAllText($settingsPath, $settingsJson, [System.Text.UTF8Encoding]::new($false))
}

function Install-PythonIfMissing {
    if (Test-Path -LiteralPath $PythonPath -PathType Leaf) {
        if (-not $PlanOnly) {
            $version = & $PythonPath -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
            if ($LASTEXITCODE -ne 0 -or $version -ne "3.12") {
                throw "Existing .venv uses Python $version. Remove or rename .venv, then rerun this script to create a Python 3.12 environment."
            }
        }
        return
    }
    $launcher = Resolve-Python312Launcher
    if (-not $launcher) {
        $winget = Get-Command winget -ErrorAction SilentlyContinue
        if (-not $winget) {
            if ($PlanOnly) {
                Write-Host "PLAN: install Python 3.12 manually, then create .venv"
                return
            }
            throw "Python 3.12 and winget are both unavailable. Install Python 3.12, then rerun this script."
        }
        Write-Step "Install Python 3.12"
        Enable-WinGetWinINetDownloader
        Invoke-External $winget.Source @(
            "install", "--id", "Python.Python.3.12", "--exact",
            "--accept-package-agreements", "--accept-source-agreements", "--silent"
        )
        if (-not $PlanOnly) {
            $launcher = Resolve-Python312Launcher
        }
    }
    if ($PlanOnly -and -not $launcher) {
        Write-Host "PLAN: py -3.12 -m venv .venv"
        return
    }
    if (-not $launcher) {
        throw "Python was installed but is not visible in this terminal. Open a new PowerShell window and rerun the script."
    }
    Write-Step "Create Python virtual environment"
    Invoke-External $launcher.Path @($launcher.Prefix + @("-m", "venv", (Join-Path $RepositoryRoot ".venv")))
}

function Install-ProjectDependencies {
    Write-Step "Install Cloud Flowing PC and voice dependencies"
    Invoke-External $PythonPath @("-m", "pip", "install", "--upgrade", "pip")
    Invoke-External $PythonPath @("-m", "pip", "install", "-e", "${RepositoryRoot}[dev,tts,voice]")
}

function Resolve-Ollama {
    $command = Get-Command ollama -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $local = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
    if (Test-Path -LiteralPath $local -PathType Leaf) { return $local }
    return $null
}

function Install-OllamaIfMissing {
    $ollama = Resolve-Ollama
    if ($ollama) { return $ollama }
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        if ($PlanOnly) {
            Write-Host "PLAN: install Ollama manually from https://ollama.com/download/windows"
            return "ollama"
        }
        throw "Ollama and winget are both unavailable. Install Ollama from https://ollama.com/download/windows, then rerun this script."
    }
    Write-Step "Install Ollama"
    Enable-WinGetWinINetDownloader
    Invoke-External $winget.Source @(
        "install", "--id", "Ollama.Ollama", "--exact",
        "--accept-package-agreements", "--accept-source-agreements", "--silent"
    )
    if ($PlanOnly) { return "ollama" }
    $ollama = Resolve-Ollama
    if (-not $ollama) {
        throw "Ollama was installed but is not visible in this terminal. Open a new PowerShell window and rerun the script."
    }
    return $ollama
}

function Wait-Ollama([string]$OllamaPath) {
    if ($PlanOnly) {
        Write-Host "PLAN: start Ollama and wait for http://127.0.0.1:11434/api/tags"
        return
    }
    try {
        Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 2 | Out-Null
        return
    } catch {
        Start-Process -FilePath $OllamaPath -ArgumentList "serve" -WindowStyle Hidden | Out-Null
    }
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Seconds 1
        try {
            Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 2 | Out-Null
            return
        } catch { }
    }
    throw "Ollama did not become ready at http://127.0.0.1:11434."
}

function Pull-OllamaModels([string]$OllamaPath) {
    Write-Step "Download Ollama models"
    foreach ($model in @($QwenModel, $LfmModel)) {
        Invoke-External $OllamaPath @("pull", $model)
    }
}

function Get-VerifiedFile {
    param(
        [string]$Uri,
        [string]$Destination,
        [string]$Sha256
    )
    if (Test-Path -LiteralPath $Destination -PathType Leaf) {
        $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $Destination).Hash.ToLowerInvariant()
        if ($actual -eq $Sha256) {
            Write-Host "Already verified: $Destination"
            return
        }
        throw "Existing file has the wrong SHA256: $Destination"
    }
    if ($PlanOnly) {
        Write-Host "PLAN: download $Uri -> $Destination"
        return
    }
    $parent = Split-Path -Parent $Destination
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $temporary = "$Destination.part"
    try {
        Invoke-WebRequest -UseBasicParsing -Uri $Uri -OutFile $temporary
        $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $temporary).Hash.ToLowerInvariant()
        if ($actual -ne $Sha256) {
            throw "SHA256 mismatch for $Uri. Expected $Sha256, got $actual."
        }
        Move-Item -LiteralPath $temporary -Destination $Destination -Force
    } finally {
        if (Test-Path -LiteralPath $temporary) {
            Remove-Item -LiteralPath $temporary -Force
        }
    }
}

function Download-FasterWhisper {
    Write-Step "Download Faster-Whisper small"
    $revision = "536b0662742c02347bc0e980a01041f333bce120"
    foreach ($file in $WhisperFiles) {
        $uri = "https://huggingface.co/Systran/faster-whisper-small/resolve/$revision/$($file.Name)?download=true"
        Get-VerifiedFile -Uri $uri -Destination (Join-Path $WhisperRoot $file.Name) -Sha256 $file.Sha256
    }
}

function Download-ZipVoice {
    if (-not $IncludeZipVoice) { return }
    Write-Step "Download ZipVoice model and vocoder"
    Write-Warning "Only use a reference WAV that you or the company has permission to use. The transcript must match it word for word."
    $cache = Join-Path $ModelRoot "downloads"
    $archive = Join-Path $cache "sherpa-onnx-zipvoice-distill-int8-zh-en-emilia.tar.bz2"
    Get-VerifiedFile -Uri $VocoderUrl -Destination $VocoderPath -Sha256 $VocoderSha256
    $decoder = Join-Path $ZipVoiceModelRoot "decoder.int8.onnx"
    $requiredRuntimeFiles = @(
        $decoder,
        (Join-Path $ZipVoiceModelRoot "encoder.int8.onnx"),
        (Join-Path $ZipVoiceModelRoot "tokens.txt"),
        (Join-Path $ZipVoiceModelRoot "lexicon.txt")
    )
    $runtimeComplete = ($requiredRuntimeFiles | Where-Object { -not (Test-Path -LiteralPath $_ -PathType Leaf) }).Count -eq 0
    $runtimeComplete = $runtimeComplete -and (Test-Path -LiteralPath (Join-Path $ZipVoiceModelRoot "espeak-ng-data") -PathType Container)
    if ($runtimeComplete) {
        $decoderHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $decoder).Hash.ToLowerInvariant()
        if ($decoderHash -eq "3cc2e08a96610d7ea1b227398e97cdbbe0414499741d3aec0b8113db2a2ab251") {
            Write-Host "Already verified: $ZipVoiceModelRoot"
            return
        }
        throw "Existing ZipVoice decoder has the wrong SHA256: $decoder"
    }
    Get-VerifiedFile -Uri $ZipVoiceArchiveUrl -Destination $archive -Sha256 $ZipVoiceArchiveSha256
    if ($PlanOnly) {
        Write-Host "PLAN: selectively extract ZipVoice with Python, skip test_wavs, then delete the archive"
        return
    }
    try {
        Invoke-External $PythonPath @(
            (Join-Path $PSScriptRoot "extract_zipvoice.py"),
            "--archive", $archive,
            "--output", $ZipVoiceRoot
        )
    } finally {
        if (Test-Path -LiteralPath $archive -PathType Leaf) {
            Remove-Item -LiteralPath $archive -Force
        }
    }
    if (-not (Test-Path -LiteralPath $decoder -PathType Leaf)) {
        throw "ZipVoice extraction completed but decoder.int8.onnx was not found."
    }
    $decoderHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $decoder).Hash.ToLowerInvariant()
    if ($decoderHash -ne "3cc2e08a96610d7ea1b227398e97cdbbe0414499741d3aec0b8113db2a2ab251") {
        throw "ZipVoice decoder SHA256 mismatch after extraction."
    }
}

function Set-EnvValues {
    param([hashtable]$Values)
    if ($PlanOnly) {
        Write-Host "PLAN: update .env with local model paths and Ollama defaults"
        return
    }
    if (-not (Test-Path -LiteralPath $EnvPath -PathType Leaf)) {
        Copy-Item -LiteralPath (Join-Path $RepositoryRoot ".env.example") -Destination $EnvPath
    }
    $lines = [System.Collections.Generic.List[string]]::new()
    foreach ($line in [System.IO.File]::ReadAllLines($EnvPath)) { $lines.Add($line) }
    foreach ($key in $Values.Keys) {
        $replacement = "$key=$($Values[$key])"
        $found = $false
        for ($index = 0; $index -lt $lines.Count; $index++) {
            if ($lines[$index] -match "^$([regex]::Escape($key))=") {
                $lines[$index] = $replacement
                $found = $true
                break
            }
        }
        if (-not $found) { $lines.Add($replacement) }
    }
    [System.IO.File]::WriteAllLines($EnvPath, $lines, [System.Text.UTF8Encoding]::new($false))
}

Set-Location $RepositoryRoot
Write-Host "Cloud Flowing PC test setup"
Write-Host "Repository: $RepositoryRoot"
Write-Host "Models: $ModelRoot"
Confirm-ModelLicenses
Install-PythonIfMissing
Install-ProjectDependencies
$ollama = Install-OllamaIfMissing
Wait-Ollama $ollama
Pull-OllamaModels $ollama
Download-FasterWhisper
Download-ZipVoice

$envValues = @{
    MODEL_PROVIDER = "ollama"
    MODEL_NAME = $QwenModel
    OLLAMA_BASE_URL = "http://127.0.0.1:11434"
    VOICE_ENABLED = "true"
    VOICE_MODEL_DIR = ".local-models/faster-whisper-small"
}
if ($IncludeZipVoice) {
    $envValues["TTS_PROVIDER"] = "disabled"
    $envValues["ZIPVOICE_MODEL_DIR"] = ".local-models/zipvoice/sherpa-onnx-zipvoice-distill-int8-zh-en-emilia"
    $envValues["ZIPVOICE_VOCODER_PATH"] = ".local-models/zipvoice/vocos_24khz.onnx"
}
Set-EnvValues $envValues

Write-Step "Setup complete"
if ($PlanOnly) {
    Write-Host "Plan-only mode made no downloads or configuration changes."
} else {
    Write-Host "Start Cloud Flowing with:"
    Write-Host "  .\.venv\Scripts\python.exe -m agent_platform.cli desktop"
    Write-Host "Switch between Qwen and LFM in the Settings page."
    if ($IncludeZipVoice) {
        Write-Host "ZipVoice stays disabled until an authorized reference WAV and exact transcript are configured."
    }
}
