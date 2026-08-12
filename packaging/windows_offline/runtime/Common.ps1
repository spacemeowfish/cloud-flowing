Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-JsonProperty {
    param(
        [Parameter(Mandatory = $true)] [object] $InputObject,
        [Parameter(Mandatory = $true)] [string] $Name,
        [object] $DefaultValue = $null
    )

    $property = $InputObject.PSObject.Properties[$Name]
    if ($null -eq $property) {
        return $DefaultValue
    }
    return $property.Value
}

function Find-BundleRoot {
    param([string] $StartDirectory = $PSScriptRoot)

    $candidate = [System.IO.Path]::GetFullPath($StartDirectory)
    for ($depth = 0; $depth -lt 6; $depth += 1) {
        if (Test-Path -LiteralPath (Join-Path $candidate "config\models.json") -PathType Leaf) {
            return $candidate
        }
        $parent = [System.IO.Directory]::GetParent($candidate)
        if ($null -eq $parent) {
            break
        }
        $candidate = $parent.FullName
    }
    throw "Cannot locate bundle root: config\models.json is missing."
}

function Resolve-BundlePath {
    param(
        [Parameter(Mandatory = $true)] [string] $BundleRoot,
        [Parameter(Mandatory = $true)] [string] $RelativePath,
        [string] $Description = "bundle path"
    )

    if ([string]::IsNullOrWhiteSpace($RelativePath)) {
        throw "$Description cannot be empty."
    }
    if ([System.IO.Path]::IsPathRooted($RelativePath)) {
        throw "$Description must be relative to the bundle root: $RelativePath"
    }

    $root = [System.IO.Path]::GetFullPath($BundleRoot).TrimEnd("\", "/")
    $resolved = [System.IO.Path]::GetFullPath((Join-Path $root $RelativePath))
    $prefix = $root + [System.IO.Path]::DirectorySeparatorChar
    if (-not $resolved.Equals($root, [System.StringComparison]::OrdinalIgnoreCase) -and
        -not $resolved.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "$Description leaves the bundle root: $RelativePath"
    }
    return $resolved
}

function Read-JsonFile {
    param(
        [Parameter(Mandatory = $true)] [string] $Path,
        [string] $Description = "JSON configuration"
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Description does not exist: $Path"
    }
    try {
        return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        throw "$Description is invalid: $($_.Exception.Message)"
    }
}

function Write-JsonAtomic {
    param(
        [Parameter(Mandatory = $true)] [string] $Path,
        [Parameter(Mandatory = $true)] [object] $Value,
        [int] $Depth = 10
    )

    $directory = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $directory -PathType Container)) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }
    $temporary = Join-Path $directory ("." + [System.IO.Path]::GetFileName($Path) + "." + [guid]::NewGuid().ToString("N") + ".tmp")
    $json = $Value | ConvertTo-Json -Depth $Depth
    [System.IO.File]::WriteAllText($temporary, $json + [Environment]::NewLine, (New-Object System.Text.UTF8Encoding($false)))
    try {
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    }
    finally {
        if (Test-Path -LiteralPath $temporary -PathType Leaf) {
            Remove-Item -LiteralPath $temporary -Force
        }
    }
}

function Write-TextAtomic {
    param(
        [Parameter(Mandatory = $true)] [string] $Path,
        [Parameter(Mandatory = $true)] [string] $Value
    )

    $directory = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $directory -PathType Container)) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }
    $temporary = Join-Path $directory ("." + [System.IO.Path]::GetFileName($Path) + "." + [guid]::NewGuid().ToString("N") + ".tmp")
    [System.IO.File]::WriteAllText($temporary, $Value, (New-Object System.Text.UTF8Encoding($false)))
    try {
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    }
    finally {
        if (Test-Path -LiteralPath $temporary -PathType Leaf) {
            Remove-Item -LiteralPath $temporary -Force
        }
    }
}

function Get-ModelsConfiguration {
    param([Parameter(Mandatory = $true)] [string] $BundleRoot)

    $path = Join-Path $BundleRoot "config\models.json"
    $configuration = Read-JsonFile -Path $path -Description "model configuration"
    $models = @(Get-JsonProperty -InputObject $configuration -Name "models" -DefaultValue @())
    if ($models.Count -lt 1) {
        throw "Model configuration must contain at least one model."
    }

    $ids = @{}
    foreach ($model in $models) {
        $id = [string](Get-JsonProperty -InputObject $model -Name "id" -DefaultValue "")
        if ($id -notmatch "^[a-z0-9][a-z0-9_-]{0,63}$") {
            throw "Invalid model id: $id"
        }
        if ($ids.ContainsKey($id)) {
            throw "Duplicate model id: $id"
        }
        $ids[$id] = $true
        $licenseAcknowledged = Get-JsonProperty -InputObject $model -Name "license_acknowledged"
        $requiredAcknowledgement = [string](Get-JsonProperty -InputObject $model -Name "required_acknowledgement" -DefaultValue "")
        if ($licenseAcknowledged -isnot [bool] -or [string]::IsNullOrWhiteSpace($requiredAcknowledgement)) {
            throw "Model $id requires a license_acknowledged boolean and required_acknowledgement text."
        }
    }
    return $configuration
}

function Get-BundleConfiguration {
    param([Parameter(Mandatory = $true)] [string] $BundleRoot)

    $path = Join-Path $BundleRoot "config\bundle.json"
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        return Read-JsonFile -Path $path -Description "bundle configuration"
    }
    return [pscustomobject]@{}
}

function Get-BundleLayout {
    param([Parameter(Mandatory = $true)] [string] $BundleRoot)

    $configuration = Get-BundleConfiguration -BundleRoot $BundleRoot
    $appRelative = [string](Get-JsonProperty -InputObject $configuration -Name "app_root" -DefaultValue "app")
    $runtime = Get-JsonProperty -InputObject $configuration -Name "runtime" -DefaultValue ([pscustomobject]@{})
    $pythonRelative = [string](Get-JsonProperty -InputObject $runtime -Name "python" -DefaultValue "runtime/python/python.exe")
    $llamaRelative = [string](Get-JsonProperty -InputObject $runtime -Name "llama_server" -DefaultValue "runtime/llama.cpp/llama-server.exe")
    return [pscustomobject]@{
        Configuration = $configuration
        AppRoot = Resolve-BundlePath -BundleRoot $BundleRoot -RelativePath $appRelative -Description "app_root"
        PythonRelative = $pythonRelative.Replace("/", "\")
        Python = Resolve-BundlePath -BundleRoot $BundleRoot -RelativePath $pythonRelative -Description "portable Python"
        LlamaRelative = $llamaRelative.Replace("/", "\")
        Llama = Resolve-BundlePath -BundleRoot $BundleRoot -RelativePath $llamaRelative -Description "llama.cpp server"
    }
}

function Resolve-ConfiguredPath {
    param(
        [Parameter(Mandatory = $true)] [string] $BundleRoot,
        [Parameter(Mandatory = $true)] [object] $Configuration,
        [Parameter(Mandatory = $true)] [string] $Name,
        [Parameter(Mandatory = $true)] [string] $DefaultValue,
        [string] $Description = "configured path"
    )

    $relative = [string](Get-JsonProperty -InputObject $Configuration -Name $Name -DefaultValue $DefaultValue)
    return Resolve-BundlePath -BundleRoot $BundleRoot -RelativePath $relative -Description $Description
}

function Get-ConfiguredModel {
    param(
        [Parameter(Mandatory = $true)] [object] $Configuration,
        [Parameter(Mandatory = $true)] [string] $ModelId
    )

    foreach ($model in @(Get-JsonProperty -InputObject $Configuration -Name "models" -DefaultValue @())) {
        if ([string](Get-JsonProperty -InputObject $model -Name "id" -DefaultValue "") -eq $ModelId) {
            return $model
        }
    }
    $known = @((Get-JsonProperty -InputObject $Configuration -Name "models" -DefaultValue @()) | ForEach-Object { $_.id }) -join ", "
    throw "Unknown model '$ModelId'. Available models: $known"
}

function Get-ActiveModelId {
    param(
        [Parameter(Mandatory = $true)] [string] $BundleRoot,
        [Parameter(Mandatory = $true)] [object] $Configuration,
        [string] $RequestedModelId = ""
    )

    if (-not [string]::IsNullOrWhiteSpace($RequestedModelId)) {
        return $RequestedModelId.Trim().ToLowerInvariant()
    }
    $activePath = Join-Path $BundleRoot "config\active-model.txt"
    if (Test-Path -LiteralPath $activePath -PathType Leaf) {
        $active = (Get-Content -LiteralPath $activePath -Raw -Encoding UTF8).Trim().ToLowerInvariant()
        if ($active) {
            return $active
        }
    }
    $defaultModel = [string](Get-JsonProperty -InputObject $Configuration -Name "default_model" -DefaultValue "")
    if ([string]::IsNullOrWhiteSpace($defaultModel)) {
        throw "Model configuration is missing default_model."
    }
    return $defaultModel.Trim().ToLowerInvariant()
}

function Assert-ModelLicenseAccepted {
    param(
        [Parameter(Mandatory = $true)] [string] $BundleRoot,
        [Parameter(Mandatory = $true)] [object] $Model
    )

    $modelId = [string]$Model.id
    $acceptancePath = Join-Path $BundleRoot "config\license-acceptance.json"
    if (-not (Test-Path -LiteralPath $acceptancePath -PathType Leaf)) {
        throw "The third-party license for model '$modelId' has not been accepted. Read THIRD_PARTY_LICENSES.md and run Accept-Licenses.cmd."
    }
    $acceptance = Read-JsonFile -Path $acceptancePath -Description "license acceptance record"
    $accepted = $false
    $direct = $acceptance.PSObject.Properties[$modelId]
    if ($null -ne $direct) {
        $accepted = $direct.Value -eq $true
    }
    $modelMap = $acceptance.PSObject.Properties["models"]
    if (-not $accepted -and $null -ne $modelMap -and $null -ne $modelMap.Value) {
        $entry = $modelMap.Value.PSObject.Properties[$modelId]
        if ($null -ne $entry) {
            $accepted = $entry.Value -eq $true
        }
    }
    if (-not $accepted) {
        $instruction = [string](Get-JsonProperty -InputObject $Model -Name "required_acknowledgement" -DefaultValue "")
        throw "Model '$modelId' has no runtime license acceptance. $instruction Run Accept-Licenses.cmd first."
    }
}

function Assert-FileHash {
    param(
        [Parameter(Mandatory = $true)] [string] $Path,
        [Parameter(Mandatory = $true)] [string] $ExpectedSha256,
        [string] $Description = "file"
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Description does not exist: $Path"
    }
    if ($ExpectedSha256 -notmatch "^[A-Fa-f0-9]{64}$") {
        throw "$Description has an invalid SHA256 value."
    }
    $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
    if (-not $actual.Equals($ExpectedSha256, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "$Description SHA256 mismatch. Expected $ExpectedSha256, got $actual."
    }
    return $actual.ToUpperInvariant()
}

function Assert-PcmWaveFile {
    param(
        [Parameter(Mandatory = $true)] [string] $Path,
        [string] $Description = "WAV"
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Description does not exist: $Path"
    }
    $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::Read)
    $reader = New-Object System.IO.BinaryReader($stream)
    try {
        if ($stream.Length -lt 44) {
            throw "$Description is not a valid WAV file: too short."
        }
        $riff = [System.Text.Encoding]::ASCII.GetString($reader.ReadBytes(4))
        [void]$reader.ReadUInt32()
        $wave = [System.Text.Encoding]::ASCII.GetString($reader.ReadBytes(4))
        if ($riff -ne "RIFF" -or $wave -ne "WAVE") {
            throw "$Description must be a RIFF/WAVE file."
        }
        $formatFound = $false
        $dataFound = $false
        $audioFormat = 0
        $channels = 0
        $sampleRate = 0
        $bitsPerSample = 0
        while ($stream.Position + 8 -le $stream.Length) {
            $chunkId = [System.Text.Encoding]::ASCII.GetString($reader.ReadBytes(4))
            $chunkSize = [int64]$reader.ReadUInt32()
            $chunkStart = $stream.Position
            if ($chunkSize -lt 0 -or $chunkStart + $chunkSize -gt $stream.Length) {
                throw "$Description contains an invalid WAV chunk."
            }
            if ($chunkId -eq "fmt ") {
                if ($chunkSize -lt 16) {
                    throw "$Description contains an invalid fmt chunk."
                }
                $audioFormat = $reader.ReadUInt16()
                $channels = $reader.ReadUInt16()
                $sampleRate = $reader.ReadUInt32()
                [void]$reader.ReadUInt32()
                [void]$reader.ReadUInt16()
                $bitsPerSample = $reader.ReadUInt16()
                $formatFound = $true
            }
            elseif ($chunkId -eq "data" -and $chunkSize -gt 0) {
                $dataFound = $true
            }
            $next = $chunkStart + $chunkSize + ($chunkSize % 2)
            if ($next -gt $stream.Length) {
                break
            }
            $stream.Position = $next
        }
        if (-not $formatFound -or -not $dataFound) {
            throw "$Description is missing fmt or a non-empty data chunk."
        }
        if ($audioFormat -ne 1 -or $channels -ne 1 -or $bitsPerSample -notin @(16, 24) -or $sampleRate -lt 8000) {
            throw "$Description must be mono PCM16/PCM24 WAV; got format=$audioFormat channels=$channels bits=$bitsPerSample rate=$sampleRate."
        }
        return [pscustomobject]@{ Channels = $channels; SampleRate = $sampleRate; BitsPerSample = $bitsPerSample }
    }
    finally {
        $reader.Dispose()
        $stream.Dispose()
    }
}

function Assert-PositiveInteger {
    param(
        [Parameter(Mandatory = $true)] [object] $Value,
        [Parameter(Mandatory = $true)] [string] $Name,
        [int] $Maximum = 32768
    )

    $parsed = 0
    if (-not [int]::TryParse([string]$Value, [ref]$parsed) -or $parsed -lt 1 -or $parsed -gt $Maximum) {
        throw "$Name must be an integer in 1..$Maximum; got '$Value'."
    }
    return $parsed
}

function Test-TcpPortOpen {
    param(
        [Parameter(Mandatory = $true)] [int] $Port,
        [int] $TimeoutMilliseconds = 400
    )

    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $result = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        if (-not $result.AsyncWaitHandle.WaitOne($TimeoutMilliseconds, $false)) {
            return $false
        }
        $client.EndConnect($result)
        return $true
    }
    catch {
        return $false
    }
    finally {
        $client.Close()
    }
}

function ConvertTo-NativeArgument {
    param([Parameter(Mandatory = $true)] [AllowEmptyString()] [string] $Argument)

    if ($Argument -notmatch '[\s"]') {
        return $Argument
    }
    $builder = New-Object System.Text.StringBuilder
    [void]$builder.Append('"')
    $backslashes = 0
    foreach ($character in $Argument.ToCharArray()) {
        if ($character -eq '\') {
            $backslashes += 1
            continue
        }
        if ($character -eq '"') {
            [void]$builder.Append(('\' * (($backslashes * 2) + 1)))
            [void]$builder.Append('"')
            $backslashes = 0
            continue
        }
        if ($backslashes -gt 0) {
            [void]$builder.Append(('\' * $backslashes))
            $backslashes = 0
        }
        [void]$builder.Append($character)
    }
    if ($backslashes -gt 0) {
        [void]$builder.Append(('\' * ($backslashes * 2)))
    }
    [void]$builder.Append('"')
    return $builder.ToString()
}

function ConvertTo-NativeArgumentList {
    param([Parameter(Mandatory = $true)] [string[]] $Arguments)
    return (($Arguments | ForEach-Object { ConvertTo-NativeArgument -Argument $_ }) -join " ")
}

function Get-ManagedProcess {
    param(
        [Parameter(Mandatory = $true)] [int] $ProcessId,
        [Parameter(Mandatory = $true)] [string] $ExpectedExecutable,
        [string[]] $CommandMarkers = @(),
        [switch] $AllowMissing
    )

    $process = Get-CimInstance -ClassName Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction Stop
    if ($null -eq $process) {
        if ($AllowMissing) {
            return $null
        }
        throw "Managed process PID $ProcessId no longer exists."
    }
    if ([string]::IsNullOrWhiteSpace([string]$process.ExecutablePath)) {
        throw "Cannot inspect executable path for PID $ProcessId; refusing the operation."
    }
    $actual = [System.IO.Path]::GetFullPath([string]$process.ExecutablePath)
    $expected = [System.IO.Path]::GetFullPath($ExpectedExecutable)
    if (-not $actual.Equals($expected, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Executable path mismatch for PID $ProcessId; refusing the operation. Expected '$expected', got '$actual'."
    }
    $commandLine = [string]$process.CommandLine
    foreach ($marker in $CommandMarkers) {
        if ([string]::IsNullOrWhiteSpace($marker)) {
            continue
        }
        if ($commandLine.IndexOf($marker, [System.StringComparison]::OrdinalIgnoreCase) -lt 0) {
            throw "Command line for PID $ProcessId lacks managed marker '$marker'; refusing the operation."
        }
    }
    return $process
}

function Stop-ManagedProcess {
    param(
        [Parameter(Mandatory = $true)] [int] $ProcessId,
        [Parameter(Mandatory = $true)] [string] $ExpectedExecutable,
        [string[]] $CommandMarkers = @(),
        [int] $TimeoutSeconds = 15
    )

    $process = Get-ManagedProcess -ProcessId $ProcessId -ExpectedExecutable $ExpectedExecutable -CommandMarkers $CommandMarkers -AllowMissing
    if ($null -eq $process) {
        return
    }
    Stop-Process -Id $ProcessId -ErrorAction Stop
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        Start-Sleep -Milliseconds 250
        $remaining = Get-CimInstance -ClassName Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction Stop
        if ($null -eq $remaining) {
            return
        }
    }
    [void](Get-ManagedProcess -ProcessId $ProcessId -ExpectedExecutable $ExpectedExecutable -CommandMarkers $CommandMarkers)
    Stop-Process -Id $ProcessId -Force -ErrorAction Stop
}

function Wait-HttpReady {
    param(
        [Parameter(Mandatory = $true)] [string] $Uri,
        [Parameter(Mandatory = $true)] [int] $ProcessId,
        [Parameter(Mandatory = $true)] [string] $ExpectedExecutable,
        [string[]] $CommandMarkers = @(),
        [int] $TimeoutSeconds = 360
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $lastError = "not responding"
    while ([DateTime]::UtcNow -lt $deadline) {
        [void](Get-ManagedProcess -ProcessId $ProcessId -ExpectedExecutable $ExpectedExecutable -CommandMarkers $CommandMarkers)
        try {
            $response = Invoke-RestMethod -Uri $Uri -Method Get -TimeoutSec 3
            if ($null -ne $response) {
                return $response
            }
        }
        catch {
            $lastError = $_.Exception.Message
        }
        Start-Sleep -Seconds 1
    }
    throw "Service was not ready within $TimeoutSeconds seconds: $Uri; last error: $lastError"
}

function Get-VoiceRuntimeConfiguration {
    param([Parameter(Mandatory = $true)] [string] $BundleRoot)

    $voiceConfigPath = Join-Path $BundleRoot "config\voices.json"
    if (-not (Test-Path -LiteralPath $voiceConfigPath -PathType Leaf)) {
        return [pscustomobject]@{ Ready = $false; Reason = "config\voices.json is missing"; LocalValidationOnly = $false; VoicesJson = "[]"; DefaultVoiceId = "" }
    }
    try {
        $configuration = Read-JsonFile -Path $voiceConfigPath -Description "voice configuration"
        $redistributionAuthorized = (Get-JsonProperty -InputObject $configuration -Name "redistribution_authorized" -DefaultValue $false) -eq $true
        $localValidationAuthorized = (Get-JsonProperty -InputObject $configuration -Name "local_validation_authorized_by_operator" -DefaultValue $false) -eq $true
        $localValidationOnly = $false
        if (-not $redistributionAuthorized -and $localValidationAuthorized) {
            $packageStatusPath = Join-Path $BundleRoot "PACKAGE-STATUS.json"
            $packageStatus = Read-JsonFile -Path $packageStatusPath -Description "package status"
            $requiredStatus = [string](Get-JsonProperty $configuration "package_status_required" "")
            $localValidationOnly = $requiredStatus -eq "NON_DISTRIBUTABLE_LOCAL_VALIDATION" -and
                ([string](Get-JsonProperty $packageStatus "status" "")) -eq "NON_DISTRIBUTABLE_LOCAL_VALIDATION" -and
                ([string](Get-JsonProperty $packageStatus "build_mode" "")) -eq "local-validation" -and
                (Get-JsonProperty $packageStatus "redistributable" $true) -eq $false
        }
        if (-not $redistributionAuthorized -and -not $localValidationOnly) {
            throw "voice rights declaration is not confirmed"
        }
        $requiredIds = @("news-female1", "male1", "female1", "female2")
        $voices = @(Get-JsonProperty -InputObject $configuration -Name "voices" -DefaultValue @())
        $runtimeVoices = @()
        foreach ($id in $requiredIds) {
            $voice = @($voices | Where-Object { [string]$_.id -eq $id })
            if ($voice.Count -ne 1) {
                throw "voice '$id' must be configured exactly once"
            }
            $voice = $voice[0]
            $wavRelative = [string](Get-JsonProperty -InputObject $voice -Name "reference_audio_path" -DefaultValue (Get-JsonProperty -InputObject $voice -Name "wav" -DefaultValue ""))
            $wavPath = Resolve-BundlePath -BundleRoot $BundleRoot -RelativePath $wavRelative -Description "voice $id WAV"
            $sha256 = [string](Get-JsonProperty -InputObject $voice -Name "sha256" -DefaultValue "")
            [void](Assert-FileHash -Path $wavPath -ExpectedSha256 $sha256 -Description "voice $id WAV")
            $transcript = [string](Get-JsonProperty -InputObject $voice -Name "reference_text" -DefaultValue (Get-JsonProperty -InputObject $voice -Name "transcript" -DefaultValue ""))
            if ([string]::IsNullOrWhiteSpace($transcript)) {
                throw "voice $id is missing an exact transcript"
            }
            $label = [string](Get-JsonProperty -InputObject $voice -Name "label" -DefaultValue $id)
            $runtimeVoices += [ordered]@{
                id = $id
                label = $label
                reference_audio_path = $wavPath
                reference_text = $transcript.Trim()
            }
        }
        $modelRelative = [string](Get-JsonProperty -InputObject $configuration -Name "model_dir" -DefaultValue "models/tts/zipvoice")
        $vocoderRelative = [string](Get-JsonProperty -InputObject $configuration -Name "vocoder_path" -DefaultValue "models/tts/vocos_24khz.onnx")
        $modelDir = Resolve-BundlePath -BundleRoot $BundleRoot -RelativePath $modelRelative -Description "ZipVoice model directory"
        $vocoderPath = Resolve-BundlePath -BundleRoot $BundleRoot -RelativePath $vocoderRelative -Description "ZipVoice vocoder"
        foreach ($required in @(
            (Join-Path $modelDir "encoder.int8.onnx"),
            (Join-Path $modelDir "decoder.int8.onnx"),
            (Join-Path $modelDir "tokens.txt"),
            (Join-Path $modelDir "lexicon.txt"),
            (Join-Path $modelDir "espeak-ng-data"),
            $vocoderPath
        )) {
            if (-not (Test-Path -LiteralPath $required)) {
                throw "missing ZipVoice resource: $required"
            }
        }
        $defaultId = [string](Get-JsonProperty -InputObject $configuration -Name "default_voice_id" -DefaultValue "news-female1")
        if ($requiredIds -notcontains $defaultId) {
            throw "default voice is not one of the four supported voices: $defaultId"
        }
        return [pscustomobject]@{
            Ready = $true
            Reason = ""
            RedistributionAuthorized = $redistributionAuthorized
            LocalValidationOnly = $localValidationOnly
            VoicesJson = ($runtimeVoices | ConvertTo-Json -Depth 5 -Compress)
            DefaultVoiceId = $defaultId
            ModelDir = $modelDir
            VocoderPath = $vocoderPath
        }
    }
    catch {
        return [pscustomobject]@{ Ready = $false; Reason = $_.Exception.Message; RedistributionAuthorized = $false; LocalValidationOnly = $false; VoicesJson = "[]"; DefaultVoiceId = "" }
    }
}

function Set-AgentRuntimeEnvironment {
    param(
        [Parameter(Mandatory = $true)] [string] $BundleRoot,
        [Parameter(Mandatory = $true)] [object] $Model,
        [Parameter(Mandatory = $true)] [int] $AgentPort,
        [Parameter(Mandatory = $true)] [int] $ModelPort
    )

    $bundleConfiguration = Get-BundleConfiguration -BundleRoot $BundleRoot
    $layout = Get-BundleLayout -BundleRoot $BundleRoot
    $paths = Get-JsonProperty -InputObject $bundleConfiguration -Name "paths" -DefaultValue ([pscustomobject]@{})
    $voiceSettings = Get-JsonProperty -InputObject $bundleConfiguration -Name "voice" -DefaultValue ([pscustomobject]@{})
    $ttsSettings = Get-JsonProperty -InputObject $bundleConfiguration -Name "tts" -DefaultValue ([pscustomobject]@{})

    $env:AGENT_APP_ROOT = $layout.AppRoot
    $env:PYTHONPATH = $layout.AppRoot
    $env:NO_PROXY = "127.0.0.1,localhost"
    $env:no_proxy = "127.0.0.1,localhost"
    $env:HF_HUB_OFFLINE = "1"
    $env:TRANSFORMERS_OFFLINE = "1"
    $env:MODEL_PROVIDER = "llamacpp"
    $env:MODEL_NAME = [string]$Model.model_name
    $env:MODEL_DIGEST = [string]$Model.sha256
    $env:MODEL_API_KEY = ""
    $env:MODEL_FALLBACK_ENABLED = "false"
    $env:LLAMACPP_SERVER_URL = "http://127.0.0.1:$ModelPort/v1"
    $env:LLAMACPP_MODEL_NAME = [string]$Model.model_name
    $env:LLAMACPP_MODEL_DIGEST = [string]$Model.sha256
    $env:LLAMACPP_THREADS = [string]$Model.threads
    $env:LLAMACPP_CONTEXT_SIZE = [string]$Model.context_size
    $env:LLAMACPP_MAX_TOKENS = [string]$Model.max_tokens
    $env:LLAMACPP_BATCH_SIZE = [string]$Model.batch_size
    $env:LLAMACPP_PARALLEL = [string]$Model.parallel
    $env:LLAMACPP_TIMEOUT_SECONDS = "180"
    $env:LLAMACPP_QUEUE_TIMEOUT_SECONDS = "5"
    $env:AGENT_HOST = "127.0.0.1"
    $env:AGENT_PORT = [string]$AgentPort
    $env:AGENT_DATABASE_PATH = Resolve-ConfiguredPath -BundleRoot $BundleRoot -Configuration $paths -Name "database" -DefaultValue "data/agent_platform.db" -Description "database path"
    $env:AGENT_AUDIT_DIR = Resolve-ConfiguredPath -BundleRoot $BundleRoot -Configuration $paths -Name "audit" -DefaultValue "logs/audit" -Description "audit path"
    $authorized = @(Get-JsonProperty -InputObject $paths -Name "authorized_files" -DefaultValue @("data/authorized_files", "demo_files"))
    $knowledge = @(Get-JsonProperty -InputObject $paths -Name "knowledge" -DefaultValue @("data/knowledge", "demo_docs"))
    $authorizedResolved = @($authorized | ForEach-Object { Resolve-BundlePath -BundleRoot $BundleRoot -RelativePath ([string]$_) -Description "authorized file root" })
    $knowledgeResolved = @($knowledge | ForEach-Object { Resolve-BundlePath -BundleRoot $BundleRoot -RelativePath ([string]$_) -Description "knowledge root" })
    $env:AGENT_AUTHORIZED_FILE_ROOTS = ConvertTo-Json -InputObject $authorizedResolved -Compress
    $env:AGENT_KNOWLEDGE_ROOTS = ConvertTo-Json -InputObject $knowledgeResolved -Compress
    $env:AGENT_MEETING_OUTPUT_DIR = Resolve-ConfiguredPath -BundleRoot $BundleRoot -Configuration $paths -Name "meeting_output" -DefaultValue "data/meeting_notes" -Description "meeting output"
    $env:AGENT_FILE_OPEN_ENABLED = "false"
    $env:AGENT_NETWORK_AVAILABLE = "false"
    $env:TTS_OUTPUT_DIR = Resolve-ConfiguredPath -BundleRoot $BundleRoot -Configuration $paths -Name "tts_output" -DefaultValue "data/tts" -Description "TTS output"

    $asrDir = Resolve-ConfiguredPath -BundleRoot $BundleRoot -Configuration $paths -Name "whisper_model" -DefaultValue "models/asr/faster-whisper-small" -Description "Whisper model"
    $asrReady = (Test-Path -LiteralPath (Join-Path $asrDir "model.bin") -PathType Leaf) -and
        (Test-Path -LiteralPath (Join-Path $asrDir "config.json") -PathType Leaf)
    $voiceRequested = (Get-JsonProperty -InputObject $voiceSettings -Name "enabled" -DefaultValue $true) -eq $true
    $env:VOICE_ENABLED = if ($asrReady -and $voiceRequested) { "true" } else { "false" }
    $env:VOICE_MODEL_DIR = $asrDir
    $env:VOICE_CPU_THREADS = [string](Assert-PositiveInteger -Value (Get-JsonProperty $voiceSettings "cpu_threads" 8) -Name "voice.cpu_threads" -Maximum 32)
    $env:VOICE_NUM_WORKERS = [string](Assert-PositiveInteger -Value (Get-JsonProperty $voiceSettings "num_workers" 1) -Name "voice.num_workers" -Maximum 4)
    $env:VOICE_BEAM_SIZE = [string](Assert-PositiveInteger -Value (Get-JsonProperty $voiceSettings "beam_size" 3) -Name "voice.beam_size" -Maximum 10)
    $env:VOICE_VAD_ENABLED = if ((Get-JsonProperty $voiceSettings "vad_enabled" $true) -eq $true) { "true" } else { "false" }
    $env:VOICE_MAX_RECORDING_SECONDS = "30"

    $tts = Get-VoiceRuntimeConfiguration -BundleRoot $BundleRoot
    $ttsRequested = [string](Get-JsonProperty -InputObject $ttsSettings -Name "provider" -DefaultValue "zipvoice") -eq "zipvoice"
    if ($tts.Ready -and $ttsRequested) {
        $env:TTS_PROVIDER = "zipvoice"
        $env:ZIPVOICE_MODEL_DIR = $tts.ModelDir
        $env:ZIPVOICE_VOCODER_PATH = $tts.VocoderPath
        $env:ZIPVOICE_VOICES = $tts.VoicesJson
        $env:ZIPVOICE_DEFAULT_VOICE_ID = $tts.DefaultVoiceId
        $env:ZIPVOICE_NUM_THREADS = [string](Assert-PositiveInteger -Value (Get-JsonProperty $ttsSettings "num_threads" 4) -Name "tts.num_threads" -Maximum 32)
        $env:ZIPVOICE_SPEED = [string](Get-JsonProperty $ttsSettings "speed" 1.0)
        $env:ZIPVOICE_NUM_STEPS = [string](Assert-PositiveInteger -Value (Get-JsonProperty $ttsSettings "num_steps" 4) -Name "tts.num_steps" -Maximum 16)
        if ($tts.LocalValidationOnly) {
            Write-Warning "NON-DISTRIBUTABLE LOCAL VALIDATION: reference voices are enabled only for this operator-authorized local smoke test. Do not share this package."
        }
    }
    else {
        $env:TTS_PROVIDER = "disabled"
        $env:ZIPVOICE_VOICES = "[]"
        Write-Warning "ZipVoice disabled: $($tts.Reason)"
    }

    return [pscustomobject]@{ AsrReady = ($asrReady -and $voiceRequested); TtsReady = ($tts.Ready -and $ttsRequested); TtsReason = $tts.Reason; TtsLocalValidationOnly = $tts.LocalValidationOnly }
}

function Get-RuntimePorts {
    param([Parameter(Mandatory = $true)] [string] $BundleRoot)

    $agentPort = 8000
    $modelPort = 8080
    $startTimeout = 360
    $config = Get-BundleConfiguration -BundleRoot $BundleRoot
    $agent = Get-JsonProperty -InputObject $config -Name "agent" -DefaultValue ([pscustomobject]@{})
    $llamacpp = Get-JsonProperty -InputObject $config -Name "llamacpp" -DefaultValue ([pscustomobject]@{})
    $agentHost = [string](Get-JsonProperty $agent "host" "127.0.0.1")
    $modelHost = [string](Get-JsonProperty $llamacpp "host" "127.0.0.1")
    if ($agentHost -ne "127.0.0.1" -or $modelHost -ne "127.0.0.1") {
        throw "Both Agent and llama.cpp must bind exactly to 127.0.0.1."
    }
    $agentPort = Assert-PositiveInteger -Value (Get-JsonProperty $agent "port" $agentPort) -Name "agent.port" -Maximum 65535
    $modelPort = Assert-PositiveInteger -Value (Get-JsonProperty $llamacpp "port" $modelPort) -Name "llamacpp.port" -Maximum 65535
    $startTimeout = Assert-PositiveInteger -Value (Get-JsonProperty $llamacpp "start_timeout_seconds" $startTimeout) -Name "llamacpp.start_timeout_seconds" -Maximum 1800
    if ($agentPort -eq $modelPort) {
        throw "Agent and model ports must be different."
    }
    return [pscustomobject]@{ Agent = $agentPort; Model = $modelPort; ModelStartTimeout = $startTimeout }
}

function Get-ServiceStatePath {
    param([Parameter(Mandatory = $true)] [string] $BundleRoot)
    return Join-Path $BundleRoot "run\service-state.json"
}

function Resolve-StateProcessExecutable {
    param(
        [Parameter(Mandatory = $true)] [string] $BundleRoot,
        [Parameter(Mandatory = $true)] [object] $StateProcess
    )
    return Resolve-BundlePath -BundleRoot $BundleRoot -RelativePath ([string]$StateProcess.executable) -Description "managed process executable"
}

function Stop-ServicesFromState {
    param(
        [Parameter(Mandatory = $true)] [string] $BundleRoot,
        [switch] $AllowMissingState
    )

    $statePath = Get-ServiceStatePath -BundleRoot $BundleRoot
    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
        if ($AllowMissingState) {
            return $false
        }
        throw "Runtime state file is missing; services may not have been started by this bundle."
    }
    $state = Read-JsonFile -Path $statePath -Description "runtime state"
    $layout = Get-BundleLayout -BundleRoot $BundleRoot
    $modelsConfiguration = Get-ModelsConfiguration -BundleRoot $BundleRoot
    $stateModelId = [string](Get-JsonProperty -InputObject $state -Name "model_id" -DefaultValue "")
    $stateModel = Get-ConfiguredModel -Configuration $modelsConfiguration -ModelId $stateModelId
    $stateModelRelative = [string](Get-JsonProperty -InputObject $stateModel -Name "path" -DefaultValue (Get-JsonProperty -InputObject $stateModel -Name "file" -DefaultValue ""))
    $stateModelPath = Resolve-BundlePath -BundleRoot $BundleRoot -RelativePath $stateModelRelative -Description "GGUF model"
    $ports = Get-RuntimePorts -BundleRoot $BundleRoot
    $validated = @()
    foreach ($name in @("agent", "model")) {
        $property = $state.PSObject.Properties[$name]
        if ($null -eq $property -or $null -eq $property.Value) {
            continue
        }
        $entry = $property.Value
        $processId = Assert-PositiveInteger -Value $entry.pid -Name "$name.pid" -Maximum 2147483647
        $reportedExecutable = Resolve-StateProcessExecutable -BundleRoot $BundleRoot -StateProcess $entry
        if ($name -eq "agent") {
            $executable = $layout.Python
            $markers = @("agent_platform.cli", "serve")
        }
        else {
            $executable = $layout.Llama
            $markers = @(
                "--model", [System.IO.Path]::GetFileName($stateModelPath),
                "--alias", [string]$stateModel.model_name,
                "--port", [string]$ports.Model
            )
        }
        if (-not $reportedExecutable.Equals($executable, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Managed $name executable in runtime state does not match the immutable bundle layout; refusing the operation."
        }
        $process = Get-ManagedProcess -ProcessId $processId -ExpectedExecutable $executable -CommandMarkers $markers -AllowMissing
        $validated += [pscustomobject]@{ ProcessId = $processId; Executable = $executable; Markers = $markers; Exists = $null -ne $process }
    }
    foreach ($entry in $validated) {
        if ($entry.Exists) {
            Stop-ManagedProcess -ProcessId $entry.ProcessId -ExpectedExecutable $entry.Executable -CommandMarkers $entry.Markers
        }
    }
    Remove-Item -LiteralPath $statePath -Force
    return $true
}
