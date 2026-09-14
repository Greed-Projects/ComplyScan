. (Join-Path $PSScriptRoot "..\common\dev-common.ps1")

Assert-BackendEnvironment

$fixturePath = Join-Path $ProjectRoot "samples\maggi-mrp-under-seal.jpeg"
$diagnosticsPath = Join-Path $BackendRoot ".diagnostics\referenced-mrp"
Assert-FileExists `
    -Path $fixturePath `
    -Description "Referenced MRP regression fixture"

Push-Location $BackendRoot
try {
    Write-Host ""
    Write-Host "=== Referenced MRP difficult-image verification ==="

    Invoke-Checked `
        -Command $BackendPython `
        -Arguments @(
            "-W", "error::DeprecationWarning",
            "-W", "error::FutureWarning",
            "scripts\verify_referenced_mrp.py",
            "--image", $fixturePath,
            "--expected-amount", "60",
            "--diagnostics-dir", $diagnosticsPath
        ) `
        -Description "Referenced MRP difficult-image verification"
}
finally {
    Pop-Location
}

Write-Host ""
Write-Host "Referenced MRP verification passed."
Write-Host "Diagnostic images: $diagnosticsPath"
