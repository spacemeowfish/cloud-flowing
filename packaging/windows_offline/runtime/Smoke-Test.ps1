[CmdletBinding()]
param(
    [switch] $KeepRunning
)

. (Join-Path $PSScriptRoot "Common.ps1")

$bundleRoot = Find-BundleRoot
$layout = Get-BundleLayout -BundleRoot $bundleRoot
$smokeScript = Resolve-BundlePath -BundleRoot $bundleRoot -RelativePath "scripts/smoke/smoke.py" -Description "smoke runner"
if (-not (Test-Path -LiteralPath $smokeScript -PathType Leaf)) {
    throw "Smoke runner is missing: $smokeScript"
}

& (Join-Path $PSScriptRoot "Self-Check.ps1")
if ($LASTEXITCODE -ne 0) {
    throw "Self-check failed; real smoke was not started."
}

$configuration = Get-ModelsConfiguration -BundleRoot $bundleRoot
$models = @($configuration.models)
if ($models.Count -lt 2) {
    throw "Real smoke requires both Qwen and LFM model entries."
}
$ports = Get-RuntimePorts -BundleRoot $bundleRoot
$reports = New-Object System.Collections.Generic.List[string]
$failed = $false

try {
    for ($index = 0; $index -lt $models.Count; $index += 1) {
        $model = $models[$index]
        $modelId = [string]$model.id
        $modelName = [string]$model.model_name
        Write-Host "Starting real smoke for $modelId ($modelName)..."
        & (Join-Path $PSScriptRoot "Start.ps1") -Model $modelId -NoBrowser
        $outputRelative = "logs/smoke/$modelId-model.json"
        & $layout.Python $smokeScript model `
            --bundle-root $bundleRoot `
            --agent-url "http://127.0.0.1:$($ports.Agent)" `
            --llama-url "http://127.0.0.1:$($ports.Model)" `
            --model-id $modelName `
            --output $outputRelative
        if ($LASTEXITCODE -ne 0) {
            $failed = $true
        }
        $reports.Add($outputRelative)
        [void](Stop-ServicesFromState -BundleRoot $bundleRoot -AllowMissingState)
    }

    $finalModel = $models[-1]
    $finalModelId = [string]$finalModel.id
    $finalModelName = [string]$finalModel.model_name
    Write-Host "Starting ASR and four-voice TTS smoke on $finalModelId..."
    & (Join-Path $PSScriptRoot "Start.ps1") -Model $finalModelId -NoBrowser
    [void](Set-AgentRuntimeEnvironment -BundleRoot $bundleRoot -Model $finalModel -AgentPort $ports.Agent -ModelPort $ports.Model)

    foreach ($phase in @("asr", "tts")) {
        $outputRelative = "logs/smoke/$phase.json"
        $arguments = @(
            $smokeScript, $phase,
            "--bundle-root", $bundleRoot,
            "--agent-url", "http://127.0.0.1:$($ports.Agent)",
            "--llama-url", "http://127.0.0.1:$($ports.Model)",
            "--model-id", $finalModelName,
            "--output", $outputRelative
        )
        if ($phase -eq "tts") {
            $arguments += @("--artifacts-dir", "logs/smoke/tts")
        }
        & $layout.Python @arguments
        if ($LASTEXITCODE -ne 0) {
            $failed = $true
        }
        $reports.Add($outputRelative)
    }
}
finally {
    if (-not $KeepRunning) {
        try { [void](Stop-ServicesFromState -BundleRoot $bundleRoot -AllowMissingState) } catch { Write-Warning $_.Exception.Message }
    }
}

Write-Host "Smoke reports:"
foreach ($report in $reports) { Write-Host "  $report" }
if ($failed) {
    throw "One or more real smoke phases failed. Inspect the reports and logs."
}
Write-Host "All real smoke phases passed." -ForegroundColor Green
