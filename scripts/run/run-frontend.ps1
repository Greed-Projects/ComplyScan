. (Join-Path $PSScriptRoot "..\common\dev-common.ps1")

Assert-CommandAvailable -Command "npm.cmd"

Push-Location $FrontendRoot
try {
    Invoke-Checked `
        -Command "npm.cmd" `
        -Arguments @("run", "dev") `
        -Description "PackCheck frontend"
}
finally {
    Pop-Location
}
