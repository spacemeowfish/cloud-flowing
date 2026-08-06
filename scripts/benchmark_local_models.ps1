param(
    [int]$Repeats = 5,
    [int]$MaxTokens = 128,
    [string]$Output = "work/local-model-validation/speed.json"
)

$ErrorActionPreference = "Stop"
$models = @(
    "qwen2.5:3b",
    "qwen3:1.7b",
    "lfm2.5-thinking:1.2b"
)
$prompt = "Generate a concise product warranty policy description. Output only the description, with no title, list, JSON, or explanation."
$results = [System.Collections.Generic.List[object]]::new()
$outputPath = Join-Path (Get-Location) $Output
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $outputPath) | Out-Null

foreach ($model in $models) {
    try { & ollama stop $model 2>$null | Out-Null } catch { }
    Start-Sleep -Milliseconds 500

    $base = @{
        model = $model
        messages = @(@{ role = "user"; content = $prompt })
        stream = $false
        think = $false
        keep_alive = "10m"
        options = @{ temperature = 0; num_predict = $MaxTokens; seed = 42 }
    }

    $warmupBody = $base | ConvertTo-Json -Depth 8
    try {
        Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/chat" -Method Post -ContentType "application/json" -Body $warmupBody | Out-Null
    } catch {
        $results.Add([pscustomobject]@{ model = $model; trial = "warmup"; error = $_.Exception.Message })
        continue
    }

    for ($trial = 1; $trial -le $Repeats; $trial++) {
        $body = $base.Clone()
        $body.options = @{ temperature = 0; num_predict = $MaxTokens; seed = 42 + $trial }
        $json = $body | ConvertTo-Json -Depth 8
        $watch = [Diagnostics.Stopwatch]::StartNew()
        try {
            $response = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/chat" -Method Post -ContentType "application/json" -Body $json
            $watch.Stop()
            $content = [string]$response.message.content
            $evalDuration = [double]$response.eval_duration
            $evalCount = [int]$response.eval_count
            $tokensPerSecond = $null
            if ($evalDuration -gt 0) {
                $tokensPerSecond = [math]::Round(($evalCount * 1e9 / $evalDuration), 2)
            }
            $results.Add([pscustomobject]@{
                model = $model
                trial = $trial
                wall_ms = [math]::Round($watch.Elapsed.TotalMilliseconds, 2)
                load_ms = [math]::Round(([double]$response.load_duration / 1e6), 2)
                prompt_eval_count = [int]$response.prompt_eval_count
                eval_count = $evalCount
                eval_ms = [math]::Round(($evalDuration / 1e6), 2)
                tokens_per_second = $tokensPerSecond
                chars = $content.Length
                done_reason = [string]$response.done_reason
            })
        } catch {
            $watch.Stop()
            $results.Add([pscustomobject]@{ model = $model; trial = $trial; wall_ms = [math]::Round($watch.Elapsed.TotalMilliseconds, 2); error = $_.Exception.Message })
        }
    }
    try { & ollama stop $model 2>$null | Out-Null } catch { }
}

$results | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $outputPath -Encoding UTF8
$results | ConvertTo-Json -Depth 8
