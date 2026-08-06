[CmdletBinding()]
param([switch]$Resume)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$cliPath = Join-Path $projectRoot ".venv\Scripts\agent-platform.exe"
$deepseekEnv = Join-Path $projectRoot ".env.deepseek"
$qwenEnv = Join-Path $projectRoot ".env.qwen"
$activeEnv = Join-Path $projectRoot ".env"
$casesDirectory = Join-Path $projectRoot "evaluation\test_cases"
$reportsDirectory = Join-Path $projectRoot "evaluation\reports"
$workDirectory = Join-Path $projectRoot "work\comparison"
$deepseekReport = Join-Path $reportsDirectory "deepseek.json"
$qwenReport = Join-Path $reportsDirectory "qwen.json"
$comparisonReport = Join-Path $reportsDirectory "comparison.md"
$script:managedProcess = $null
$script:managedPids = @()

function Get-EnvValue([string]$Path, [string]$Name) {
    $line = Get-Content -LiteralPath $Path -Encoding UTF8 | Where-Object { $_ -like "$Name=*" } | Select-Object -First 1
    if (-not $line) { return $null }
    return $line.Substring($Name.Length + 1).Trim()
}

function Stop-ManagedService {
    foreach ($processId in ($script:managedPids | Sort-Object -Descending -Unique)) {
        Stop-Process -Id $processId -ErrorAction SilentlyContinue
    }
    if ($script:managedProcess -and -not $script:managedProcess.HasExited) {
        Stop-Process -Id $script:managedProcess.Id -ErrorAction SilentlyContinue
    }
    $script:managedPids = @()
    $script:managedProcess = $null
}

function Stop-ExistingProjectService([int]$Port) {
    $listeners = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
    foreach ($listener in $listeners) {
        $child = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
        $parent = Get-CimInstance Win32_Process -Filter "ProcessId=$($child.ParentProcessId)" -ErrorAction SilentlyContinue
        $parentPath = if ($parent) { [string]$parent.ExecutablePath } else { "" }
        $belongsToProject = $child.CommandLine -like "*agent_platform.cli serve*" -and $parentPath.StartsWith(
            $projectRoot,
            [StringComparison]::OrdinalIgnoreCase
        )
        if (-not $belongsToProject) {
            throw "Port $Port is owned by a non-project process (PID $($listener.OwningProcess))."
        }
        Stop-Process -Id $child.ProcessId -ErrorAction SilentlyContinue
        if ($parent) { Stop-Process -Id $parent.ProcessId -ErrorAction SilentlyContinue }
    }
}

function Test-Prerequisites {
    foreach ($path in ($pythonPath, $cliPath, $deepseekEnv, $qwenEnv, $casesDirectory)) {
        if (-not (Test-Path -LiteralPath $path)) { throw "Missing prerequisite: $path" }
    }
    $caseCount = 0
    foreach ($file in Get-ChildItem -LiteralPath $casesDirectory -Filter "*.json") {
        $fileCases = Get-Content -LiteralPath $file.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
        $caseCount += $fileCases.Count
    }
    if ($caseCount -ne 60) { throw "Expected 60 fixed cases, found $caseCount." }

    $deepseekKey = Get-EnvValue $deepseekEnv "MODEL_API_KEY"
    if ([string]::IsNullOrWhiteSpace($deepseekKey)) { throw ".env.deepseek has no MODEL_API_KEY." }
    if ((Get-EnvValue $qwenEnv "MODEL_NAME") -ne "qwen2.5:3b") {
        throw ".env.qwen MODEL_NAME must be qwen2.5:3b."
    }
    try {
        $tags = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 5
    } catch {
        throw "Ollama is unavailable at http://127.0.0.1:11434: $($_.Exception.Message)"
    }
    $availableModels = @($tags.models | ForEach-Object { $_.name })
    if ($availableModels -notcontains "qwen2.5:3b") {
        throw "Ollama model qwen2.5:3b is missing. Available: $($availableModels -join ', ')"
    }
    Write-Host "Prerequisites passed: 60 cases and Ollama qwen2.5:3b ready."
}

function Test-CompleteReport([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $false }
    try {
        $report = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
        return [bool]($report.metrics -and $report.per_intent -and $report.metrics.total -eq 60)
    } catch {
        return $false
    }
}

function Wait-QwenWarmup {
    $body = @{
        model = "qwen2.5:3b"
        messages = @(@{ role = "user"; content = "Return JSON: {`"ready`": true}" })
        temperature = 0
        response_format = @{ type = "json_object" }
    } | ConvertTo-Json -Depth 8
    $lastError = $null
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        try {
            $response = Invoke-RestMethod -Uri "http://127.0.0.1:11434/v1/chat/completions" `
                -Method Post -ContentType "application/json" -Body $body -TimeoutSec 120
            if ($response.choices.Count -gt 0) {
                Write-Host "Qwen inference warmup passed."
                return
            }
        } catch {
            $lastError = $_.Exception.Message
            if ($attempt -lt 3) { Start-Sleep -Seconds 2 }
        }
    }
    throw "Qwen failed all 3 inference warmup attempts: $lastError"
}

function Start-HealthService([string]$Slug, [int]$Port) {
    $stdout = Join-Path $workDirectory "$Slug-service.stdout.log"
    $stderr = Join-Path $workDirectory "$Slug-service.stderr.log"
    $priorDatabase = $env:AGENT_DATABASE_PATH
    $priorAudit = $env:AGENT_AUDIT_DIR
    try {
        $env:AGENT_DATABASE_PATH = "./work/comparison/$Slug-health-$PID.db"
        $env:AGENT_AUDIT_DIR = "./work/comparison/$Slug-audit-$PID"
        $script:managedProcess = Start-Process -FilePath $pythonPath `
            -ArgumentList "-m", "agent_platform.cli", "serve" `
            -WorkingDirectory $projectRoot -WindowStyle Hidden `
            -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
    } finally {
        if ($null -eq $priorDatabase) { Remove-Item Env:AGENT_DATABASE_PATH -ErrorAction SilentlyContinue }
        else { $env:AGENT_DATABASE_PATH = $priorDatabase }
        if ($null -eq $priorAudit) { Remove-Item Env:AGENT_AUDIT_DIR -ErrorAction SilentlyContinue }
        else { $env:AGENT_AUDIT_DIR = $priorAudit }
    }

    $health = $null
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 3
            break
        } catch {
            if ($attempt -lt 3) { Start-Sleep -Seconds 2 }
        }
    }
    if (-not $health -or $health.status -ne "ok") {
        $details = if (Test-Path -LiteralPath $stderr) { Get-Content -LiteralPath $stderr -Raw -Encoding UTF8 } else { "No service log." }
        throw "$Slug service failed all 3 health retries. $details"
    }
    $listeners = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
    $script:managedPids = @($script:managedProcess.Id) + @($listeners | ForEach-Object { $_.OwningProcess })
    Write-Host "$Slug service is healthy; provider=$($health.model_provider)."
}

function Invoke-ModelEvaluation([string]$Slug, [string]$EnvFile, [string]$OutputFile) {
    $port = [int](Get-EnvValue $EnvFile "AGENT_PORT")
    $priorNoProxy = $env:NO_PROXY
    if ($Slug -eq "qwen") {
        $bypass = @("127.0.0.1", "localhost", "::1")
        if (-not [string]::IsNullOrWhiteSpace($priorNoProxy)) { $bypass += $priorNoProxy }
        $env:NO_PROXY = $bypass -join ","
    }
    try {
        Copy-Item -LiteralPath $EnvFile -Destination $activeEnv -Force
        Stop-ExistingProjectService $port
        Start-HealthService $Slug $port
        if ($Slug -eq "qwen") { Wait-QwenWarmup }
        $stdout = Join-Path $workDirectory "$Slug-evaluate.stdout.log"
        $stderr = Join-Path $workDirectory "$Slug-evaluate.stderr.log"
        $quotedOutputFile = '"' + $OutputFile + '"'
        Write-Host "Starting 60-case $Slug evaluation..."
        $evaluation = Start-Process -FilePath $cliPath `
            -ArgumentList "evaluate", "--mode", "cloud", "--output", $quotedOutputFile `
            -WorkingDirectory $projectRoot -WindowStyle Hidden `
            -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru -Wait
        if ($evaluation.ExitCode -ne 0) {
            $details = if (Test-Path -LiteralPath $stderr) { Get-Content -LiteralPath $stderr -Raw -Encoding UTF8 } else { "No evaluation log." }
            throw "$Slug evaluation failed (exit=$($evaluation.ExitCode)). $details"
        }
        $report = Get-Content -LiteralPath $OutputFile -Raw -Encoding UTF8 | ConvertFrom-Json
        if (-not $report.metrics -or -not $report.per_intent -or $report.metrics.total -ne 60) {
            throw "$Slug report is invalid or does not contain all 60 cases."
        }
        Write-Host "$Slug evaluation complete; intent accuracy=$([math]::Round($report.metrics.intent_accuracy * 100, 1))%."
    } finally {
        Stop-ManagedService
        if ($null -eq $priorNoProxy) { Remove-Item Env:NO_PROXY -ErrorAction SilentlyContinue }
        else { $env:NO_PROXY = $priorNoProxy }
    }
}

New-Item -ItemType Directory -Force -Path $reportsDirectory, $workDirectory | Out-Null
$env:PYTHONUTF8 = "1"

try {
    Test-Prerequisites
    if ($Resume -and (Test-CompleteReport $deepseekReport)) {
        Write-Host "Resume: using existing complete deepseek.json."
    } else {
        Invoke-ModelEvaluation "deepseek" $deepseekEnv $deepseekReport
    }
    if ($Resume -and (Test-CompleteReport $qwenReport)) {
        Write-Host "Resume: using existing complete qwen.json."
    } else {
        Invoke-ModelEvaluation "qwen" $qwenEnv $qwenReport
    }
    & $pythonPath (Join-Path $projectRoot "evaluation\compare_reports.py") `
        --deepseek $deepseekReport --qwen $qwenReport --cases $casesDirectory --output $comparisonReport
    if ($LASTEXITCODE -ne 0) { throw "Failed to generate comparison.md." }
    Write-Host "Comparison complete: $comparisonReport"
} finally {
    Stop-ManagedService
    Copy-Item -LiteralPath $deepseekEnv -Destination $activeEnv -Force
    Write-Host "Restored .env.deepseek as the default configuration."
}
