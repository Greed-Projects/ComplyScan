Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$BackendScript = Join-Path $PSScriptRoot "run-backend.ps1"
$FrontendScript = Join-Path $PSScriptRoot "run-frontend.ps1"

foreach ($scriptPath in @($BackendScript, $FrontendScript)) {
    if (-not (Test-Path -LiteralPath $scriptPath -PathType Leaf)) {
        throw "Required run script not found: $scriptPath"
    }
}

$commonArguments = @(
    "-NoLogo",
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-NoExit"
)

Start-Process `
    -FilePath "pwsh.exe" `
    -ArgumentList ($commonArguments + @("-File", "`"$BackendScript`""))

Start-Process `
    -FilePath "pwsh.exe" `
    -ArgumentList ($commonArguments + @("-File", "`"$FrontendScript`""))
