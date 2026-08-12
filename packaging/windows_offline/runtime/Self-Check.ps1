[CmdletBinding()]
param(
    [switch] $Fast,
    [switch] $AllowMissingVoices
)

. (Join-Path $PSScriptRoot "Common.ps1")

$bundleRoot = Find-BundleRoot
$failures = New-Object System.Collections.Generic.List[string]
$warnings = New-Object System.Collections.Generic.List[string]
$passes = New-Object System.Collections.Generic.List[string]
$hashCache = @{}

function Add-CheckFailure([string] $Message) { $script:failures.Add($Message) }
function Add-CheckWarning([string] $Message) { $script:warnings.Add($Message) }
function Add-CheckPass([string] $Message) { $script:passes.Add($Message) }

if (-not [System.Runtime.InteropServices.RuntimeInformation]::IsOSPlatform([System.Runtime.InteropServices.OSPlatform]::Windows)) {
    Add-CheckFailure "Requires Windows x64."
}
elseif ([System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture -ne [System.Runtime.InteropServices.Architecture]::X64) {
    Add-CheckFailure "Requires x64 Windows; detected $([System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture)."
}
else {
    Add-CheckPass "Windows x64"
}

$layout = $null
$bundleConfiguration = Get-BundleConfiguration -BundleRoot $bundleRoot
try { $layout = Get-BundleLayout -BundleRoot $bundleRoot } catch { Add-CheckFailure $_.Exception.Message }
$bundlePaths = Get-JsonProperty -InputObject $bundleConfiguration -Name "paths" -DefaultValue ([pscustomobject]@{})
$whisperRelative = [string](Get-JsonProperty $bundlePaths "whisper_model" "models/asr/faster-whisper-small")
$voiceConfigPath = Join-Path $bundleRoot "config\voices.json"
$voiceConfiguration = if (Test-Path -LiteralPath $voiceConfigPath -PathType Leaf) { Read-JsonFile -Path $voiceConfigPath -Description "voice configuration" } else { [pscustomobject]@{} }
$zipvoiceRelative = [string](Get-JsonProperty $voiceConfiguration "model_dir" "models/tts/zipvoice")
$vocoderRelative = [string](Get-JsonProperty $voiceConfiguration "vocoder_path" "models/tts/vocos_24khz.onnx")
$requiredFiles = @(
    [pscustomobject]@{ Name = "portable Python"; Path = if ($null -ne $layout) { $layout.Python } else { "" } },
    [pscustomobject]@{ Name = "llama.cpp server"; Path = if ($null -ne $layout) { $layout.Llama } else { "" } },
    [pscustomobject]@{ Name = "Agent CLI"; Path = if ($null -ne $layout) { Join-Path $layout.AppRoot "agent_platform\cli.py" } else { "" } },
    [pscustomobject]@{ Name = "Whisper model.bin"; Path = Resolve-BundlePath $bundleRoot ($whisperRelative + "/model.bin") },
    [pscustomobject]@{ Name = "Whisper config.json"; Path = Resolve-BundlePath $bundleRoot ($whisperRelative + "/config.json") },
    [pscustomobject]@{ Name = "ZipVoice encoder"; Path = Resolve-BundlePath $bundleRoot ($zipvoiceRelative + "/encoder.int8.onnx") },
    [pscustomobject]@{ Name = "ZipVoice decoder"; Path = Resolve-BundlePath $bundleRoot ($zipvoiceRelative + "/decoder.int8.onnx") },
    [pscustomobject]@{ Name = "ZipVoice tokens"; Path = Resolve-BundlePath $bundleRoot ($zipvoiceRelative + "/tokens.txt") },
    [pscustomobject]@{ Name = "ZipVoice lexicon"; Path = Resolve-BundlePath $bundleRoot ($zipvoiceRelative + "/lexicon.txt") },
    [pscustomobject]@{ Name = "ZipVoice vocoder"; Path = Resolve-BundlePath $bundleRoot $vocoderRelative }
)
foreach ($required in $requiredFiles) {
    try {
        if ([string]::IsNullOrWhiteSpace([string]$required.Path) -or -not (Test-Path -LiteralPath $required.Path -PathType Leaf)) {
            throw "missing"
        }
        Add-CheckPass $required.Name
    }
    catch {
        Add-CheckFailure "Missing required resource: $($required.Name)"
    }
}
$espeak = Resolve-BundlePath $bundleRoot ($zipvoiceRelative + "/espeak-ng-data")
if (Test-Path -LiteralPath $espeak -PathType Container) { Add-CheckPass "ZipVoice espeak-ng-data" } else { Add-CheckFailure "Missing ZipVoice espeak-ng-data" }

try {
    $configuration = Get-ModelsConfiguration -BundleRoot $bundleRoot
    foreach ($model in @($configuration.models)) {
        try {
            $modelRelative = [string](Get-JsonProperty -InputObject $model -Name "path" -DefaultValue (Get-JsonProperty -InputObject $model -Name "file" -DefaultValue ""))
            $modelPath = Resolve-BundlePath -BundleRoot $bundleRoot -RelativePath $modelRelative -Description "GGUF model"
            if ($Fast) {
                if (-not (Test-Path -LiteralPath $modelPath -PathType Leaf)) { throw "file missing" }
                Add-CheckPass "Model $($model.id) exists (hash skipped by -Fast)"
            }
            else {
                $hash = Assert-FileHash -Path $modelPath -ExpectedSha256 ([string]$model.sha256) -Description "GGUF model $($model.id)"
                $hashCache[$modelPath.ToLowerInvariant()] = $hash
                Add-CheckPass "Model $($model.id) SHA256"
            }
            Assert-ModelLicenseAccepted -BundleRoot $bundleRoot -Model $model
            Add-CheckPass "Model $($model.id) license accepted"
        }
        catch {
            Add-CheckFailure $_.Exception.Message
        }
    }
}
catch {
    Add-CheckFailure $_.Exception.Message
}

$voiceStatus = Get-VoiceRuntimeConfiguration -BundleRoot $bundleRoot
if ($voiceStatus.Ready) {
    if ($voiceStatus.LocalValidationOnly) {
        Add-CheckPass "Four operator-authorized local-validation ZipVoice presets"
        Add-CheckWarning "NON-DISTRIBUTABLE LOCAL VALIDATION voices are enabled for local smoke only. DO NOT SHARE THIS PACKAGE."
    }
    else {
        Add-CheckPass "Four redistribution-authorized ZipVoice presets"
    }
}
elseif ($AllowMissingVoices) {
    Add-CheckWarning "ZipVoice disabled: $($voiceStatus.Reason)"
}
else {
    Add-CheckFailure "ZipVoice is not ready: $($voiceStatus.Reason)"
}

$python = if ($null -ne $layout) { $layout.Python } else { "" }
if (Test-Path -LiteralPath $python -PathType Leaf) {
    try {
        $version = & $python -c "import platform,sys; assert sys.maxsize > 2**32; print(platform.python_version())" 2>&1
        if ($LASTEXITCODE -ne 0) { throw ($version -join " ") }
        Add-CheckPass "Portable Python $($version[-1])"
        $imports = & $python -c "import agent_platform, faster_whisper, numpy, sherpa_onnx, sounddevice; print('runtime imports ok')" 2>&1
        if ($LASTEXITCODE -ne 0) { throw ($imports -join " ") }
        Add-CheckPass "Python runtime imports"
    }
    catch {
        Add-CheckFailure "Portable Python validation failed: $($_.Exception.Message)"
    }
}

if (-not $Fast) {
    $sumsPath = Join-Path $bundleRoot "SHA256SUMS"
    if (Test-Path -LiteralPath $sumsPath -PathType Leaf) {
        $lineNumber = 0
        foreach ($line in Get-Content -LiteralPath $sumsPath -Encoding UTF8) {
            $lineNumber += 1
            $trimmed = $line.Trim()
            if (-not $trimmed -or $trimmed.StartsWith("#")) { continue }
            if ($trimmed -notmatch "^([A-Fa-f0-9]{64})\s+\*?(.+)$") {
                Add-CheckFailure "SHA256SUMS line $lineNumber is invalid."
                continue
            }
            try {
                $expected = $Matches[1]
                $relative = $Matches[2].Trim().Replace("/", "\")
                $path = Resolve-BundlePath -BundleRoot $bundleRoot -RelativePath $relative -Description "SHA256SUMS entry"
                $cacheKey = $path.ToLowerInvariant()
                $actual = if ($hashCache.ContainsKey($cacheKey)) { $hashCache[$cacheKey] } else { (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash }
                if (-not $actual.Equals($expected, [System.StringComparison]::OrdinalIgnoreCase)) {
                    throw "expected $expected, got $actual"
                }
            }
            catch {
                Add-CheckFailure "SHA256SUMS $relative failed: $($_.Exception.Message)"
            }
        }
        if (-not ($failures | Where-Object { $_ -like "SHA256SUMS*" })) {
            Add-CheckPass "SHA256SUMS"
        }
    }
    else {
        Add-CheckFailure "SHA256SUMS is missing."
    }
}
else {
    Add-CheckWarning "-Fast skipped model and package hashes. Run Self-Check.cmd without -Fast before acceptance."
}

try {
    $ports = Get-RuntimePorts -BundleRoot $bundleRoot
    foreach ($port in @($ports.Agent, $ports.Model)) {
        if (Test-TcpPortOpen -Port $port) { Add-CheckWarning "127.0.0.1:$port is already in use." } else { Add-CheckPass "Port $port available" }
    }
}
catch {
    Add-CheckFailure $_.Exception.Message
}

Write-Host ""
Write-Host "Self-check summary"
Write-Host "  Passed: $($passes.Count)"
Write-Host "  Warnings: $($warnings.Count)"
Write-Host "  Failed: $($failures.Count)"
foreach ($warning in $warnings) { Write-Warning $warning }
foreach ($failure in $failures) { Write-Host "FAILED: $failure" -ForegroundColor Red }
if ($failures.Count -gt 0) {
    exit 1
}
Write-Host "Offline bundle self-check passed." -ForegroundColor Green
