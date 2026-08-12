[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)] [string] $SourceDirectory
)

. (Join-Path $PSScriptRoot "Common.ps1")

$bundleRoot = Find-BundleRoot
$sourceRoot = [System.IO.Path]::GetFullPath($SourceDirectory).TrimEnd("\", "/")
if (-not (Test-Path -LiteralPath $sourceRoot -PathType Container)) {
    throw "Voice import directory does not exist: $sourceRoot"
}
$manifestPath = Join-Path $sourceRoot "voices-import.json"
$manifest = Read-JsonFile -Path $manifestPath -Description "voice import manifest"
$authorization = Get-JsonProperty -InputObject $manifest -Name "authorization"
if ($null -eq $authorization) {
    throw "voices-import.json is missing authorization."
}
$requiredDeclaration = "I confirm that I have the right to use and redistribute these four reference audio files in this internal test package."
$declaration = [string](Get-JsonProperty -InputObject $authorization -Name "declaration" -DefaultValue "")
$authorizedBy = [string](Get-JsonProperty -InputObject $authorization -Name "authorized_by" -DefaultValue "")
$evidence = [string](Get-JsonProperty -InputObject $authorization -Name "evidence" -DefaultValue "")
if (-not $declaration.Equals($requiredDeclaration, [System.StringComparison]::Ordinal) -or
    [string]::IsNullOrWhiteSpace($authorizedBy) -or [string]::IsNullOrWhiteSpace($evidence)) {
    throw "Voice import requires the exact authorization declaration, authorized_by, and evidence fields. See INSTALL.md."
}

$requiredIds = @("news-female1", "male1", "female1", "female2")
$manifestVoices = @(Get-JsonProperty -InputObject $manifest -Name "voices" -DefaultValue @())
if ($manifestVoices.Count -ne 4) {
    throw "Voice import must contain exactly four entries."
}
$validated = @()
foreach ($id in $requiredIds) {
    $matches = @($manifestVoices | Where-Object { [string]$_.id -eq $id })
    if ($matches.Count -ne 1) {
        throw "Voice '$id' must appear exactly once."
    }
    $voice = $matches[0]
    $relative = [string](Get-JsonProperty -InputObject $voice -Name "reference_audio_path" -DefaultValue (Get-JsonProperty -InputObject $voice -Name "wav" -DefaultValue ""))
    if ([System.IO.Path]::IsPathRooted($relative) -or [string]::IsNullOrWhiteSpace($relative)) {
        throw "Voice '$id' wav must be a relative path."
    }
    $sourcePath = [System.IO.Path]::GetFullPath((Join-Path $sourceRoot $relative))
    $sourcePrefix = $sourceRoot + [System.IO.Path]::DirectorySeparatorChar
    if (-not $sourcePath.StartsWith($sourcePrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Voice '$id' wav leaves the import directory."
    }
    $transcript = [string](Get-JsonProperty -InputObject $voice -Name "reference_text" -DefaultValue (Get-JsonProperty -InputObject $voice -Name "transcript" -DefaultValue ""))
    if ([string]::IsNullOrWhiteSpace($transcript)) {
        throw "Voice '$id' transcript is required and must exactly match the WAV."
    }
    $sha256 = [string](Get-JsonProperty -InputObject $voice -Name "sha256" -DefaultValue "")
    [void](Assert-FileHash -Path $sourcePath -ExpectedSha256 $sha256 -Description "Voice '$id'")
    [void](Assert-PcmWaveFile -Path $sourcePath -Description "Voice '$id'")
    $validated += [pscustomobject]@{
        id = $id
        label = [string](Get-JsonProperty -InputObject $voice -Name "label" -DefaultValue $id)
        source = $sourcePath
        transcript = $transcript.Trim()
        sha256 = $sha256.ToUpperInvariant()
    }
}

$defaultVoiceId = [string](Get-JsonProperty -InputObject $manifest -Name "default_voice_id" -DefaultValue "news-female1")
if ($requiredIds -notcontains $defaultVoiceId) {
    throw "default_voice_id must be one of: $($requiredIds -join ', ')"
}
$voicesDirectory = Join-Path $bundleRoot "voices"
$runDirectory = Join-Path $bundleRoot "run"
foreach ($directory in @($voicesDirectory, $runDirectory)) {
    if (-not (Test-Path -LiteralPath $directory -PathType Container)) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }
}
$staging = Join-Path $runDirectory ("voice-import-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $staging | Out-Null
try {
    foreach ($voice in $validated) {
        Copy-Item -LiteralPath $voice.source -Destination (Join-Path $staging ($voice.id + ".wav"))
    }
    foreach ($voice in $validated) {
        $staged = Join-Path $staging ($voice.id + ".wav")
        [void](Assert-FileHash -Path $staged -ExpectedSha256 $voice.sha256 -Description "Staged voice '$($voice.id)'")
    }

    $versionId = [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ") + "-" + [guid]::NewGuid().ToString("N").Substring(0, 8)
    $versionRelative = "voices/imports/$versionId"
    $versionDirectory = Join-Path $voicesDirectory ("imports\" + $versionId)
    $versionsRoot = Split-Path -Parent $versionDirectory
    if (-not (Test-Path -LiteralPath $versionsRoot -PathType Container)) {
        New-Item -ItemType Directory -Path $versionsRoot -Force | Out-Null
    }
    Move-Item -LiteralPath $staging -Destination $versionDirectory
    $staging = $versionDirectory
    $voiceEntries = @($validated | ForEach-Object {
        [ordered]@{
            id = $_.id
            label = $_.label
            reference_audio_path = "$versionRelative/$($_.id).wav"
            reference_text = $_.transcript
            sha256 = $_.sha256
        }
    })
    $existingVoiceConfigPath = Join-Path $bundleRoot "config\voices.json"
    $existingVoiceConfig = if (Test-Path -LiteralPath $existingVoiceConfigPath -PathType Leaf) {
        Read-JsonFile -Path $existingVoiceConfigPath -Description "existing voice configuration"
    } else {
        [pscustomobject]@{}
    }
    $configuration = [ordered]@{
        schema_version = 1
        redistribution_authorized = $true
        source_notice = $evidence.Trim()
        authorized_by = $authorizedBy.Trim()
        imported_at_utc = [DateTime]::UtcNow.ToString("o")
        model_dir = [string](Get-JsonProperty $existingVoiceConfig "model_dir" "models/tts/zipvoice")
        vocoder_path = [string](Get-JsonProperty $existingVoiceConfig "vocoder_path" "models/tts/vocos_24khz.onnx")
        default_voice_id = $defaultVoiceId
        voices = $voiceEntries
    }
    Write-JsonAtomic -Path (Join-Path $bundleRoot "config\voices.json") -Value $configuration
    $staging = ""
    Write-Host "Four authorized ZipVoice presets imported successfully. Restart Cloud Flowing to enable TTS."
}
finally {
    if (-not [string]::IsNullOrWhiteSpace($staging)) {
        $stagingFull = [System.IO.Path]::GetFullPath($staging)
        $runPrefix = [System.IO.Path]::GetFullPath($runDirectory).TrimEnd("\") + "\"
        $importsPrefix = [System.IO.Path]::GetFullPath((Join-Path $voicesDirectory "imports")).TrimEnd("\") + "\"
        if (($stagingFull.StartsWith($runPrefix, [System.StringComparison]::OrdinalIgnoreCase) -or
            $stagingFull.StartsWith($importsPrefix, [System.StringComparison]::OrdinalIgnoreCase)) -and
            (Test-Path -LiteralPath $stagingFull -PathType Container)) {
            [System.IO.Directory]::Delete($stagingFull, $true)
        }
    }
}
