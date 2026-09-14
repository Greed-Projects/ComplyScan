Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$BackendVerifier = Join-Path $PSScriptRoot "verify-backend.ps1"
$FrontendVerifier = Join-Path $PSScriptRoot "verify-frontend.ps1"

Write-Host ""
Write-Host "======================================="
Write-Host " PackCheck AI - Full Verification"
Write-Host "======================================="

& $BackendVerifier
& $FrontendVerifier

Write-Host ""
Write-Host "======================================="
Write-Host " All verification checks passed."
Write-Host "======================================="
