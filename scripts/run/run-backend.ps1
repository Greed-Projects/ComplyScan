. (Join-Path $PSScriptRoot "..\common\dev-common.ps1")

Assert-BackendEnvironment

Push-Location $BackendRoot
try {
    Invoke-Checked `
        -Command $BackendPython `
        -Arguments @(
            "-W", "error::DeprecationWarning",
            "-W", "error::FutureWarning",
            "-m", "uvicorn",
            "app.main:app",
            "--host", "127.0.0.1",
            "--port", "8000",
            "--ws", "none"
        ) `
        -Description "PackCheck backend"
}
finally {
    Pop-Location
}
