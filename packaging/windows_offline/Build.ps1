[CmdletBinding()]
param(
    [ValidateSet("local-validation", "distributable")] [string] $Mode = "local-validation",
    [Parameter(Mandatory = $true)] [string] $QwenModel,
    [Parameter(Mandatory = $true)] [string] $LfmModel,
    [Parameter(Mandatory = $true)] [string] $WhisperModel,
    [Parameter(Mandatory = $true)] [string] $ZipVoiceModel,
    [Parameter(Mandatory = $true)] [string] $ZipVoiceVocoder,
    [Parameter(Mandatory = $true)] [string] $PythonArchive,
    [Parameter(Mandatory = $true)] [string] $LlamaArchive,
    [Parameter(Mandatory = $true)] [string] $Wheelhouse,
    [Parameter(Mandatory = $true)] [string] $Output,
    [string] $LocalVoiceSmokeSource = "",
    [string] $RightsAssertions = "",
    [string] $HostPython = "python",
    [string] $BundleName = "cloud-flowing-windows-x64-offline",
    [string] $SourceCommit = "",
    [switch] $Replace,
    [switch] $Archive
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$arguments = @(
    (Join-Path $PSScriptRoot "build_bundle.py"),
    "--mode", $Mode,
    "--qwen-model", $QwenModel,
    "--lfm-model", $LfmModel,
    "--whisper-model", $WhisperModel,
    "--zipvoice-model", $ZipVoiceModel,
    "--zipvoice-vocoder", $ZipVoiceVocoder,
    "--python-archive", $PythonArchive,
    "--llama-archive", $LlamaArchive,
    "--wheelhouse", $Wheelhouse,
    "--output", $Output,
    "--bundle-name", $BundleName
)
if ($LocalVoiceSmokeSource) { $arguments += @("--local-voice-smoke-source", $LocalVoiceSmokeSource) }
if ($RightsAssertions) { $arguments += @("--rights-assertions", $RightsAssertions) }
if ($SourceCommit) { $arguments += @("--source-commit", $SourceCommit) }
if ($Replace) { $arguments += "--replace" }
if ($Archive) { $arguments += "--archive" }

& $HostPython @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Offline bundle build failed with exit code $LASTEXITCODE."
}
