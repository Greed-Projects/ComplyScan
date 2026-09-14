. (Join-Path $PSScriptRoot "..\common\dev-common.ps1")

Assert-BackendEnvironment
Assert-FileExists `
    -Path $SampleLabelPath `
    -Description "OCR verification sample image"

Push-Location $BackendRoot
try {
    Write-Host ""
    Write-Host "=== Backend dependency verification ==="

    Invoke-Checked `
        -Command $BackendPython `
        -Arguments @("-m", "pip", "check") `
        -Description "Backend dependency verification"

    Write-Host ""
    Write-Host "=== Backend automated tests ==="

    Invoke-Checked `
        -Command $BackendPython `
        -Arguments @(
            "-W", "error::DeprecationWarning",
            "-W", "error::FutureWarning",
            "-m", "pytest", "-q"
        ) `
        -Description "Backend automated tests"

    Write-Host ""
    Write-Host "=== OCR runtime verification ==="

    Invoke-Checked `
        -Command $BackendPython `
        -Arguments @(
            "-W", "error::DeprecationWarning",
            "-W", "error::FutureWarning",
            "scripts\verify_ocr_runtime.py",
            "--warmup-image", $SampleLabelPath
        ) `
        -Description "OCR runtime verification"
}
finally {
    Pop-Location
}

Write-Host ""
Write-Host "Backend verification passed."
