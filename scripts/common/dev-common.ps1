Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$script:ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$script:BackendRoot = Join-Path $ProjectRoot "backend"
$script:FrontendRoot = Join-Path $ProjectRoot "frontend"
$script:BackendPython = Join-Path $BackendRoot ".venv\Scripts\python.exe"
$script:SampleLabelPath = Join-Path $ProjectRoot "samples\sample-label.png"

function Assert-CommandAvailable {
    param(
        [Parameter(Mandatory)]
        [string] $Command
    )

    if (-not (Get-Command $Command -ErrorAction SilentlyContinue)) {
        throw "Required command was not found on PATH: $Command"
    }
}

function Assert-FileExists {
    param(
        [Parameter(Mandatory)]
        [string] $Path,

        [Parameter(Mandatory)]
        [string] $Description
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Description not found: $Path"
    }
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory)]
        [string] $Command,

        [Parameter()]
        [string[]] $Arguments = @(),

        [Parameter()]
        [string] $Description = $Command
    )

    & $Command @Arguments
    $exitCode = $LASTEXITCODE

    if ($exitCode -ne 0) {
        throw "$Description failed with exit code $exitCode."
    }
}

function Assert-BackendEnvironment {
    Assert-FileExists `
        -Path $BackendPython `
        -Description "Backend virtual-environment Python"
}
