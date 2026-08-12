[CmdletBinding()]
param(
    [string] $Model = "",
    [switch] $NoBrowser
)

. (Join-Path $PSScriptRoot "Common.ps1")

$bundleRoot = Find-BundleRoot
$modelsConfiguration = Get-ModelsConfiguration -BundleRoot $bundleRoot
$modelId = Get-ActiveModelId -BundleRoot $bundleRoot -Configuration $modelsConfiguration -RequestedModelId $Model
$selectedModel = Get-ConfiguredModel -Configuration $modelsConfiguration -ModelId $modelId
Assert-ModelLicenseAccepted -BundleRoot $bundleRoot -Model $selectedModel

$layout = Get-BundleLayout -BundleRoot $bundleRoot
$pythonRelative = $layout.PythonRelative
$llamaRelative = $layout.LlamaRelative
$pythonPath = $layout.Python
$llamaPath = $layout.Llama
$modelRelative = [string](Get-JsonProperty -InputObject $selectedModel -Name "path" -DefaultValue (Get-JsonProperty -InputObject $selectedModel -Name "file" -DefaultValue ""))
$modelPath = Resolve-BundlePath -BundleRoot $bundleRoot -RelativePath $modelRelative -Description "GGUF model"

foreach ($required in @($pythonPath, $llamaPath, $modelPath, (Join-Path $layout.AppRoot "agent_platform"))) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Required bundle resource is missing: $required"
    }
}
[void](Assert-FileHash -Path $modelPath -ExpectedSha256 ([string]$selectedModel.sha256) -Description "GGUF model $modelId")

$threads = Assert-PositiveInteger -Value $selectedModel.threads -Name "$modelId.threads" -Maximum 32
$contextSize = Assert-PositiveInteger -Value $selectedModel.context_size -Name "$modelId.context_size" -Maximum 32768
$maxTokens = Assert-PositiveInteger -Value $selectedModel.max_tokens -Name "$modelId.max_tokens" -Maximum 8192
$batchSize = Assert-PositiveInteger -Value $selectedModel.batch_size -Name "$modelId.batch_size" -Maximum 4096
$parallel = Assert-PositiveInteger -Value $selectedModel.parallel -Name "$modelId.parallel" -Maximum 8
$ports = Get-RuntimePorts -BundleRoot $bundleRoot

$statePath = Get-ServiceStatePath -BundleRoot $bundleRoot
if (Test-Path -LiteralPath $statePath -PathType Leaf) {
    $existing = Read-JsonFile -Path $statePath -Description "runtime state"
    $live = @()
    foreach ($name in @("model", "agent")) {
        $property = $existing.PSObject.Properties[$name]
        if ($null -eq $property -or $null -eq $property.Value) {
            continue
        }
        $entry = $property.Value
        $processId = Assert-PositiveInteger -Value $entry.pid -Name "$name.pid" -Maximum 2147483647
        $executable = Resolve-StateProcessExecutable -BundleRoot $bundleRoot -StateProcess $entry
        $markers = @((Get-JsonProperty -InputObject $entry -Name "command_markers" -DefaultValue @()) | ForEach-Object { [string]$_ })
        $process = Get-ManagedProcess -ProcessId $processId -ExpectedExecutable $executable -CommandMarkers $markers -AllowMissing
        if ($null -ne $process) {
            $live += "$name PID $processId"
        }
    }
    if ($live.Count -gt 0) {
        throw "Bundle services are already running ($($live -join ', ')). Use Stop.cmd first."
    }
    Remove-Item -LiteralPath $statePath -Force
}

foreach ($port in @($ports.Model, $ports.Agent)) {
    if (Test-TcpPortOpen -Port $port) {
        throw "Port 127.0.0.1:$port is already in use. Change config/runtime.json or stop the conflicting service."
    }
}

foreach ($relativeDirectory in @("data", "data\authorized_files", "data\knowledge", "data\meeting_notes", "data\tts", "logs", "logs\audit", "run")) {
    $directory = Join-Path $bundleRoot $relativeDirectory
    if (-not (Test-Path -LiteralPath $directory -PathType Container)) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }
}

$features = Set-AgentRuntimeEnvironment -BundleRoot $bundleRoot -Model $selectedModel -AgentPort $ports.Agent -ModelPort $ports.Model
$timestamp = [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ")
$modelStdout = Join-Path $bundleRoot "logs\llama-$modelId-$timestamp.stdout.log"
$modelStderr = Join-Path $bundleRoot "logs\llama-$modelId-$timestamp.stderr.log"
$agentStdout = Join-Path $bundleRoot "logs\agent-$modelId-$timestamp.stdout.log"
$agentStderr = Join-Path $bundleRoot "logs\agent-$modelId-$timestamp.stderr.log"

$modelArguments = @(
    "--model", $modelPath,
    "--alias", [string]$selectedModel.model_name,
    "--host", "127.0.0.1",
    "--port", [string]$ports.Model,
    "--threads", [string]$threads,
    "--ctx-size", [string]$contextSize,
    "--batch-size", [string]$batchSize,
    "--parallel", [string]$parallel,
    "--jinja"
)
$modelMarkers = @("--model", [System.IO.Path]::GetFileName($modelPath), "--alias", [string]$selectedModel.model_name, "--port", [string]$ports.Model)
$agentMarkers = @("agent_platform.cli", "serve")
$modelProcess = $null
$agentProcess = $null

try {
    $modelProcess = Start-Process -FilePath $llamaPath `
        -ArgumentList (ConvertTo-NativeArgumentList -Arguments $modelArguments) `
        -WorkingDirectory $bundleRoot `
        -RedirectStandardOutput $modelStdout `
        -RedirectStandardError $modelStderr `
        -WindowStyle Hidden `
        -PassThru

    $state = [ordered]@{
        schema_version = 1
        model_id = $modelId
        started_at_utc = [DateTime]::UtcNow.ToString("o")
        model = [ordered]@{
            pid = $modelProcess.Id
            executable = $llamaRelative
            command_markers = $modelMarkers
        }
        agent = $null
    }
    Write-JsonAtomic -Path $statePath -Value $state

    [void](Wait-HttpReady -Uri "http://127.0.0.1:$($ports.Model)/health" `
        -ProcessId $modelProcess.Id `
        -ExpectedExecutable $llamaPath `
        -CommandMarkers $modelMarkers `
        -TimeoutSeconds $ports.ModelStartTimeout)

    $agentArguments = @("-m", "agent_platform.cli", "serve")
    $agentProcess = Start-Process -FilePath $pythonPath `
        -ArgumentList (ConvertTo-NativeArgumentList -Arguments $agentArguments) `
        -WorkingDirectory $layout.AppRoot `
        -RedirectStandardOutput $agentStdout `
        -RedirectStandardError $agentStderr `
        -WindowStyle Hidden `
        -PassThru

    $state.agent = [ordered]@{
        pid = $agentProcess.Id
        executable = $pythonRelative
        command_markers = $agentMarkers
    }
    Write-JsonAtomic -Path $statePath -Value $state

    $health = Wait-HttpReady -Uri "http://127.0.0.1:$($ports.Agent)/health" `
        -ProcessId $agentProcess.Id `
        -ExpectedExecutable $pythonPath `
        -CommandMarkers $agentMarkers `
        -TimeoutSeconds 120
    if ([string]$health.status -ne "ok" -or [string]$health.model_provider -ne "llamacpp") {
        throw "Agent health response is not the expected llama.cpp runtime."
    }

    Write-TextAtomic -Path (Join-Path $bundleRoot "config\active-model.txt") -Value ($modelId + [Environment]::NewLine)
    Write-Host "Cloud Flowing is ready."
    Write-Host "Model: $modelId ($([string]$selectedModel.model_name))"
    Write-Host "Workbench: http://127.0.0.1:$($ports.Agent)/"
    Write-Host "ASR: $(if ($features.AsrReady) { 'enabled' } else { 'disabled (model missing)' })"
    Write-Host "TTS: $(if ($features.TtsReady) { 'enabled' } else { 'disabled: ' + $features.TtsReason })"
    if ($features.TtsLocalValidationOnly) {
        Write-Host "WARNING: NON-DISTRIBUTABLE LOCAL VALIDATION PACKAGE. DO NOT SHARE." -ForegroundColor Red
    }
    if (-not $NoBrowser) {
        Start-Process "http://127.0.0.1:$($ports.Agent)/"
    }
}
catch {
    if ($null -ne $agentProcess) {
        try { Stop-ManagedProcess -ProcessId $agentProcess.Id -ExpectedExecutable $pythonPath -CommandMarkers $agentMarkers -TimeoutSeconds 5 } catch { Write-Warning $_.Exception.Message }
    }
    if ($null -ne $modelProcess) {
        try { Stop-ManagedProcess -ProcessId $modelProcess.Id -ExpectedExecutable $llamaPath -CommandMarkers $modelMarkers -TimeoutSeconds 5 } catch { Write-Warning $_.Exception.Message }
    }
    if (Test-Path -LiteralPath $statePath -PathType Leaf) {
        Remove-Item -LiteralPath $statePath -Force
    }
    throw
}
