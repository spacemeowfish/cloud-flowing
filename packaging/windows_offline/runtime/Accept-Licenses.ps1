[CmdletBinding()]
param(
    [switch] $AcceptAll
)

. (Join-Path $PSScriptRoot "Common.ps1")

$bundleRoot = Find-BundleRoot
$configuration = Get-ModelsConfiguration -BundleRoot $bundleRoot
$licenseDocument = Join-Path $bundleRoot "THIRD_PARTY_LICENSES.md"
if (-not (Test-Path -LiteralPath $licenseDocument -PathType Leaf)) {
    throw "THIRD_PARTY_LICENSES.md is missing; license acceptance cannot proceed."
}

Write-Host "Read before accepting: $licenseDocument"
Write-Host "Acceptance records a local runtime decision only; it does not grant redistribution rights."
$acceptedModels = [ordered]@{}
foreach ($model in @($configuration.models)) {
    $id = [string]$model.id
    $instruction = [string]$model.required_acknowledgement
    $accepted = $AcceptAll
    if (-not $accepted) {
        Write-Host ""
        Write-Host "Model: $id"
        Write-Host $instruction
        $answer = Read-Host "Type I ACCEPT to accept this model license"
        $accepted = $answer.Trim().Equals("I ACCEPT", [System.StringComparison]::Ordinal)
    }
    $acceptedModels[$id] = [bool]$accepted
}

if (@($acceptedModels.Values | Where-Object { $_ -eq $true }).Count -eq 0) {
    throw "No model license was accepted; no acceptance file was written."
}
$record = [ordered]@{
    schema_version = 1
    accepted_at_utc = [DateTime]::UtcNow.ToString("o")
    notice = "Local runtime acknowledgement only; see THIRD_PARTY_LICENSES.md."
    models = $acceptedModels
}
Write-JsonAtomic -Path (Join-Path $bundleRoot "config\license-acceptance.json") -Value $record
Write-Host "License acceptance saved to config\license-acceptance.json."
