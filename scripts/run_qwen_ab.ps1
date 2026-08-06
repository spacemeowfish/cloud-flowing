[CmdletBinding()]
param(
    [string]$PreviousReport = "evaluation/reports/qwen2.5-3b-v2.3-60.json",
    [string]$PreviousRaw = "evaluation/reports/qwen2.5-3b-v2.3-60.raw.jsonl",
    [string]$Output = "evaluation/reports/qwen2.5-3b-v3.1-staged-60.json",
    [string]$RawOutput = "evaluation/reports/qwen2.5-3b-v3.1-staged-60.raw.jsonl",
    [string]$PromptVersion = "qwen2.5-3b-staged-v3.1"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$qwenEnv = Join-Path $projectRoot ".env.qwen"
$cases = Join-Path $projectRoot "evaluation\test_cases"
$previousReportPath = [IO.Path]::GetFullPath((Join-Path $projectRoot $PreviousReport))
$previousRawPath = [IO.Path]::GetFullPath((Join-Path $projectRoot $PreviousRaw))
$outputPath = [IO.Path]::GetFullPath((Join-Path $projectRoot $Output))
$rawOutputPath = [IO.Path]::GetFullPath((Join-Path $projectRoot $RawOutput))

foreach ($path in ($python, $qwenEnv, $cases, $previousReportPath, $previousRawPath)) {
    if (-not (Test-Path -LiteralPath $path)) { throw "Missing prerequisite: $path" }
}

$caseCount = 0
foreach ($file in Get-ChildItem -LiteralPath $cases -Filter "*.json") {
    $fileCases = Get-Content -LiteralPath $file.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
    $caseCount += $fileCases.Count
}
if ($caseCount -ne 60) { throw "Expected 60 fixed cases, found $caseCount." }

$savedEnvironment = @{}
try {
    foreach ($line in Get-Content -LiteralPath $qwenEnv -Encoding UTF8) {
        if ($line -notmatch '^([^#=]+)=(.*)$') { continue }
        $name = $Matches[1].Trim()
        $value = $Matches[2].Trim()
        $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
        [Environment]::SetEnvironmentVariable($name, $value, "Process")
    }
    $savedEnvironment["NO_PROXY"] = [Environment]::GetEnvironmentVariable("NO_PROXY", "Process")
    $savedEnvironment["PYTHONUTF8"] = [Environment]::GetEnvironmentVariable("PYTHONUTF8", "Process")
    $env:NO_PROXY = "127.0.0.1,localhost,::1"
    $env:PYTHONUTF8 = "1"

    $tags = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 10
    $model = $tags.models | Where-Object { $_.name -eq "qwen2.5:3b" } | Select-Object -First 1
    if (-not $model) { throw "Ollama model qwen2.5:3b is unavailable." }
    $digest = [string]$model.digest
    if ([string]::IsNullOrWhiteSpace($digest)) { throw "Ollama did not return a model digest." }

    New-Item -ItemType Directory -Force -Path (Split-Path $outputPath), (Split-Path $rawOutputPath) | Out-Null
    & $python -m agent_platform.cli evaluate --mode cloud --cases $cases --detailed --expected-total 60 `
        --previous-report $previousReportPath --previous-raw-snapshot $previousRawPath `
        --output $outputPath --capture-raw $rawOutputPath `
        --prompt-version $PromptVersion --model-digest $digest
    if ($LASTEXITCODE -ne 0) { throw "Qwen A/B evaluation failed with exit code $LASTEXITCODE." }

    $report = Get-Content -LiteralPath $outputPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $rawLines = @(Get-Content -LiteralPath $rawOutputPath -Encoding UTF8 | Where-Object { $_.Trim() })
    if ($report.metrics.total -ne 60 -or $rawLines.Count -ne 60) {
        throw "Incomplete A/B artifacts: report total=$($report.metrics.total), raw lines=$($rawLines.Count)."
    }
    Write-Host "Qwen A/B complete: $outputPath"
    Write-Host "digest=$digest; prompt=$PromptVersion; intent=$([math]::Round($report.metrics.intent_accuracy * 100, 2))%; e2e=$([math]::Round($report.detailed.metrics.end_to_end_accuracy * 100, 2))%"
} finally {
    foreach ($name in $savedEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], "Process")
    }
}
