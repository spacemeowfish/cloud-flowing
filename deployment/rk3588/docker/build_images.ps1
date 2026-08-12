param(
    [ValidateSet('qwen', 'lfm', 'all')]
    [string]$Model = 'all',
    [string]$OutputDirectory = 'dist/rk3588',
    [switch]$PackageOnly
)

$ErrorActionPreference = 'Stop'
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$lock = Get-Content -Raw -Encoding utf8 (Join-Path $PSScriptRoot 'models.lock.json') | ConvertFrom-Json
$destinationRoot = Join-Path $repositoryRoot $OutputDirectory
New-Item -ItemType Directory -Force -Path $destinationRoot | Out-Null

function Build-ModelImage([string]$Name) {
    $spec = $lock.$Name
    $modelPath = Join-Path $repositoryRoot (Join-Path 'models' $spec.filename)
    if (-not (Test-Path -LiteralPath $modelPath -PathType Leaf)) {
        throw "Missing model file: $modelPath. Run prepare_models.py first."
    }
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $modelPath).Hash.ToLowerInvariant()
    if ($actual -ne $spec.sha256) {
        throw "SHA256 mismatch for $modelPath. Expected $($spec.sha256), got $actual"
    }
    $archive = Join-Path $destinationRoot "cloud-flowing-$Name-rk3588-cpu-poc.tar"
    & docker buildx build `
        --platform linux/arm64 `
        --file (Join-Path $PSScriptRoot 'Dockerfile.cpu-poc') `
        --tag $spec.image `
        --build-arg "MODEL_FILE=$($spec.filename)" `
        --build-arg "MODEL_NAME=$Name" `
        --build-arg "MODEL_SHA256=$($spec.sha256)" `
        --output "type=docker,dest=$archive" `
        $repositoryRoot
    if ($LASTEXITCODE -ne 0) { throw "docker buildx failed for $Name" }
    Write-Host "Created $archive"
}

function Copy-PackageSupport([string]$TargetDirectory) {
    Copy-Item -Force (Join-Path $PSScriptRoot 'install.sh') $TargetDirectory
    Copy-Item -Force (Join-Path $PSScriptRoot 'board_probe.sh') $TargetDirectory
    Copy-Item -Force (Join-Path $PSScriptRoot 'benchmark_profiles.py') $TargetDirectory
    Copy-Item -Force (Join-Path $PSScriptRoot 'README.md') $TargetDirectory
    Copy-Item -Force (Join-Path $PSScriptRoot 'RK3588-USAGE.md') $TargetDirectory
}

function New-ModelPackage([string]$Name) {
    $archiveName = "cloud-flowing-$Name-rk3588-cpu-poc.tar"
    $archive = Join-Path $destinationRoot $archiveName
    if (-not (Test-Path -LiteralPath $archive -PathType Leaf)) {
        throw "Missing built image archive: $archive"
    }
    $packageRoot = Join-Path (Split-Path -Parent $destinationRoot) "rk3588-$Name"
    New-Item -ItemType Directory -Force -Path $packageRoot | Out-Null
    $otherName = if ($Name -eq 'qwen') { 'lfm' } else { 'qwen' }
    $otherArchive = Join-Path $packageRoot "cloud-flowing-$otherName-rk3588-cpu-poc.tar"
    if (Test-Path -LiteralPath $otherArchive) {
        Remove-Item -LiteralPath $otherArchive
    }
    Copy-Item -Force -LiteralPath $archive -Destination (Join-Path $packageRoot $archiveName)
    $digest = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash.ToLowerInvariant()
    Set-Content -LiteralPath (Join-Path $packageRoot 'SHA256SUMS') -Value "$digest  $archiveName" -Encoding ascii
    $packageManifest = @(
        "model=$Name",
        "image=$($lock.$Name.image)",
        "archive=$archiveName",
        "install=sh install.sh $Name ./$archiveName --skip-pressure",
        "usage=RK3588-USAGE.md"
    )
    Set-Content -LiteralPath (Join-Path $packageRoot 'PACKAGE-MANIFEST.txt') -Value $packageManifest -Encoding ascii
    Copy-PackageSupport $packageRoot
    Write-Host "Packaged $Name delivery at $packageRoot"
}

$names = if ($Model -eq 'all') { @('qwen', 'lfm') } else { @($Model) }
if (-not $PackageOnly) {
    foreach ($name in $names) { Build-ModelImage $name }
}
$checksumLines = Get-ChildItem -LiteralPath $destinationRoot -Filter '*.tar' -File |
    Sort-Object Name |
    ForEach-Object {
        $digest = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLowerInvariant()
        "$digest  $($_.Name)"
    }
Set-Content -LiteralPath (Join-Path $destinationRoot 'SHA256SUMS') -Value $checksumLines -Encoding ascii
Copy-PackageSupport $destinationRoot
foreach ($name in $names) { New-ModelPackage $name }
