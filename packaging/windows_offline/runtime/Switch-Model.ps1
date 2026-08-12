[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)] [string] $Model,
    [switch] $NoBrowser
)

. (Join-Path $PSScriptRoot "Common.ps1")

$bundleRoot = Find-BundleRoot
$configuration = Get-ModelsConfiguration -BundleRoot $bundleRoot
$newModelId = $Model.Trim().ToLowerInvariant()
$newModel = Get-ConfiguredModel -Configuration $configuration -ModelId $newModelId
Assert-ModelLicenseAccepted -BundleRoot $bundleRoot -Model $newModel
$newModelRelative = [string](Get-JsonProperty -InputObject $newModel -Name "path" -DefaultValue (Get-JsonProperty -InputObject $newModel -Name "file" -DefaultValue ""))
$newModelPath = Resolve-BundlePath -BundleRoot $bundleRoot -RelativePath $newModelRelative -Description "GGUF model"
[void](Assert-FileHash -Path $newModelPath -ExpectedSha256 ([string]$newModel.sha256) -Description "GGUF model $newModelId")

$activePath = Join-Path $bundleRoot "config\active-model.txt"
$oldModelId = Get-ActiveModelId -BundleRoot $bundleRoot -Configuration $configuration
if ($oldModelId -eq $newModelId) {
    $statePath = Get-ServiceStatePath -BundleRoot $bundleRoot
    if (Test-Path -LiteralPath $statePath -PathType Leaf) {
        Write-Host "Model '$newModelId' is already active. Restarting the full stack."
    }
}

[void](Stop-ServicesFromState -BundleRoot $bundleRoot -AllowMissingState)
Write-TextAtomic -Path $activePath -Value ($newModelId + [Environment]::NewLine)
try {
    & (Join-Path $PSScriptRoot "Start.ps1") -Model $newModelId -NoBrowser:$NoBrowser
    Write-Host "Model switch completed: $oldModelId -> $newModelId"
}
catch {
    $switchError = $_
    Write-Warning "Model '$newModelId' failed to start. Restoring '$oldModelId'."
    Write-TextAtomic -Path $activePath -Value ($oldModelId + [Environment]::NewLine)
    try {
        & (Join-Path $PSScriptRoot "Start.ps1") -Model $oldModelId -NoBrowser
    }
    catch {
        Write-Warning "Rollback model '$oldModelId' also failed: $($_.Exception.Message)"
    }
    throw $switchError
}
