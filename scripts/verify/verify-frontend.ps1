. (Join-Path $PSScriptRoot "..\common\dev-common.ps1")

Assert-CommandAvailable -Command "npm.cmd"

Push-Location $FrontendRoot
try {
    Write-Host ""
    Write-Host "=== Frontend dependency audit ==="

    Invoke-Checked `
        -Command "npm.cmd" `
        -Arguments @("audit") `
        -Description "Frontend dependency audit"

    Write-Host ""
    Write-Host "=== TypeScript verification ==="

    Invoke-Checked `
        -Command "npm.cmd" `
        -Arguments @("run", "typecheck") `
        -Description "TypeScript verification"

    Write-Host ""
    Write-Host "=== ESLint verification ==="

    Invoke-Checked `
        -Command "npm.cmd" `
        -Arguments @("run", "lint") `
        -Description "ESLint verification"

    Write-Host ""
    Write-Host "=== Next.js production build ==="

    Invoke-Checked `
        -Command "npm.cmd" `
        -Arguments @("run", "build") `
        -Description "Next.js production build"
}
finally {
    Pop-Location
}

Write-Host ""
Write-Host "Frontend verification passed."
