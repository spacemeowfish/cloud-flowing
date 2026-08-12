[CmdletBinding()]
param(
    [string] $Model = "",
    [switch] $NoBrowser
)

& (Join-Path $PSScriptRoot "Start.ps1") -Model $Model -NoBrowser:$NoBrowser
