[CmdletBinding()]
param()

. (Join-Path $PSScriptRoot "Common.ps1")

$bundleRoot = Find-BundleRoot
$stopped = Stop-ServicesFromState -BundleRoot $bundleRoot -AllowMissingState
if ($stopped) {
    Write-Host "Cloud Flowing services stopped."
}
else {
    Write-Host "Cloud Flowing services are not running (no managed state file)."
}
