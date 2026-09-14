[CmdletBinding()]
param(
    [switch] $SkipOcrWarmup,
    [switch] $RecreateBackend,
    [string] $PythonExecutable
)

. (Join-Path $PSScriptRoot "..\common\dev-common.ps1")

$VenvRoot = Join-Path $BackendRoot ".venv"

function Get-PythonRuntimeInfo {
    param(
        [Parameter(Mandatory)]
        [string] $Executable
    )

    try {
        $output = & $Executable -c "import sys; print(f'{sys.version_info.major}|{sys.version_info.minor}|{sys.version_info.micro}|{sys.executable}')" 2>$null
        $exitCode = $LASTEXITCODE
    }
    catch {
        return $null
    }

    if ($exitCode -ne 0 -or -not $output) {
        return $null
    }

    $line = (@($output) | Select-Object -Last 1).ToString().Trim()
    $parts = $line -split '\|', 4

    if ($parts.Count -ne 4) {
        return $null
    }

    return [pscustomobject]@{
        Major      = [int] $parts[0]
        Minor      = [int] $parts[1]
        Patch      = [int] $parts[2]
        Executable = $parts[3]
        Version    = "$($parts[0]).$($parts[1]).$($parts[2])"
    }
}

function Resolve-PackCheckPython {
    param(
        [string] $RequestedExecutable
    )

    $seen = @{}
    $detected = [System.Collections.Generic.List[object]]::new()

    function Add-Candidate {
        param(
            [string] $Candidate,
            [string] $Source
        )

        if ([string]::IsNullOrWhiteSpace($Candidate)) {
            return $null
        }

        try {
            if (Test-Path -LiteralPath $Candidate -PathType Leaf) {
                $resolved = (Resolve-Path -LiteralPath $Candidate).Path
            }
            else {
                $command = Get-Command $Candidate -ErrorAction Stop
                $resolved = if ($command.Path) { $command.Path } else { $command.Source }
            }
        }
        catch {
            return $null
        }

        if ([string]::IsNullOrWhiteSpace($resolved)) {
            return $null
        }

        $key = $resolved.ToLowerInvariant()
        if ($seen.ContainsKey($key)) {
            return $null
        }
        $seen[$key] = $true

        $runtime = Get-PythonRuntimeInfo -Executable $resolved
        if ($null -eq $runtime) {
            return $null
        }

        $entry = [pscustomobject]@{
            Source     = $Source
            Runtime    = $runtime
            Executable = $runtime.Executable
        }
        $detected.Add($entry)

        if ($runtime.Major -eq 3 -and $runtime.Minor -eq 13) {
            return $entry
        }

        return $null
    }

    if (-not [string]::IsNullOrWhiteSpace($RequestedExecutable)) {
        $selected = Add-Candidate -Candidate $RequestedExecutable -Source "-PythonExecutable"
        if ($null -ne $selected) {
            return $selected
        }

        $requestedInfo = $detected | Select-Object -Last 1
        if ($null -ne $requestedInfo) {
            throw "-PythonExecutable must point to Python 3.13.x. Found Python $($requestedInfo.Runtime.Version): $($requestedInfo.Executable)"
        }

        throw "-PythonExecutable could not be resolved or executed: $RequestedExecutable"
    }

    # Prefer the Windows Python launcher because it selects a version explicitly
    # and is unaffected by which `python.exe` happens to be first on PATH.
    foreach ($launcherName in @("py.exe", "py")) {
        $launcherCommands = @(Get-Command $launcherName -All -ErrorAction SilentlyContinue)
        foreach ($launcher in $launcherCommands) {
            $launcherPath = if ($launcher.Path) { $launcher.Path } else { $launcher.Source }
            if ([string]::IsNullOrWhiteSpace($launcherPath)) {
                continue
            }

            try {
                $resolvedFromLauncher = & $launcherPath -3.13 -c "import sys; print(sys.executable)" 2>$null
                $launcherExitCode = $LASTEXITCODE
            }
            catch {
                $launcherExitCode = 1
                $resolvedFromLauncher = $null
            }

            if ($launcherExitCode -eq 0 -and $resolvedFromLauncher) {
                $candidatePath = (@($resolvedFromLauncher) | Select-Object -Last 1).ToString().Trim()
                $selected = Add-Candidate -Candidate $candidatePath -Source "$launcherName -3.13"
                if ($null -ne $selected) {
                    return $selected
                }
            }
        }
    }

    # Prefer version-specific PATH commands before generic `python`.
    foreach ($commandName in @("python3.13.exe", "python3.13")) {
        foreach ($command in @(Get-Command $commandName -All -ErrorAction SilentlyContinue)) {
            $candidatePath = if ($command.Path) { $command.Path } else { $command.Source }
            $selected = Add-Candidate -Candidate $candidatePath -Source $commandName
            if ($null -ne $selected) {
                return $selected
            }
        }
    }

    # Search the standard python.org per-user installation location. This also
    # works when Python 3.13 is installed but was not added to PATH.
    if (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        $localPythonRoot = Join-Path $env:LOCALAPPDATA "Programs\Python"
        if (Test-Path -LiteralPath $localPythonRoot -PathType Container) {
            foreach ($directory in @(Get-ChildItem -LiteralPath $localPythonRoot -Directory -Filter "Python313*" -ErrorAction SilentlyContinue)) {
                $selected = Add-Candidate -Candidate (Join-Path $directory.FullName "python.exe") -Source "LocalAppData"
                if ($null -ne $selected) {
                    return $selected
                }
            }
        }
    }

    # Also support machine-wide python.org installations.
    if (-not [string]::IsNullOrWhiteSpace($env:ProgramFiles)) {
        foreach ($directory in @(Get-ChildItem -Path (Join-Path $env:ProgramFiles "Python313*") -Directory -ErrorAction SilentlyContinue)) {
            $selected = Add-Candidate -Candidate (Join-Path $directory.FullName "python.exe") -Source "ProgramFiles"
            if ($null -ne $selected) {
                return $selected
            }
        }
    }

    # Finally inspect every generic Python command on PATH instead of accepting
    # only the first one. Multiple installed versions are therefore safe.
    foreach ($commandName in @("python.exe", "python")) {
        foreach ($command in @(Get-Command $commandName -All -ErrorAction SilentlyContinue)) {
            $candidatePath = if ($command.Path) { $command.Path } else { $command.Source }
            $selected = Add-Candidate -Candidate $candidatePath -Source $commandName
            if ($null -ne $selected) {
                return $selected
            }
        }
    }

    $detectedText = if ($detected.Count -gt 0) {
        ($detected | ForEach-Object {
            "  - Python $($_.Runtime.Version) [$($_.Source)] $($_.Executable)"
        }) -join [Environment]::NewLine
    }
    else {
        "  - No runnable Python installation was discovered."
    }

    throw @"
PackCheck requires CPython 3.13.x, but no compatible interpreter was found.
Detected Python installations:
$detectedText

Install Python 3.13.x, or provide its exact executable explicitly:
  .\scripts\setup\bootstrap-windows.ps1 -PythonExecutable "C:\Path\To\Python313\python.exe"

The bootstrap does not require Python 3.13 to be the first `python` on PATH.
"@
}

function Invoke-PipChecked {
    param(
        [Parameter(Mandatory)]
        [string[]] $Arguments,

        [Parameter(Mandatory)]
        [string] $Description
    )

    & $BackendPython -m pip @Arguments 2>&1 | Tee-Object -Variable pipLines
    $exitCode = $LASTEXITCODE

    if ($exitCode -ne 0) {
        throw "$Description failed with exit code $exitCode."
    }

    $deprecationLines = @(
        $pipLines | Where-Object {
            "$_" -match '(?i)\bDEPRECATION\b|\bdeprecated\b'
        }
    )

    if ($deprecationLines.Count -gt 0) {
        throw "$Description emitted a deprecation warning. Resolve it before continuing."
    }
}

function Invoke-NpmInstallChecked {
    param(
        [Parameter(Mandatory)]
        [ValidateSet("ci", "install")]
        [string] $Subcommand
    )

    & npm.cmd $Subcommand 2>&1 | Tee-Object -Variable npmLines
    $exitCode = $LASTEXITCODE

    if ($exitCode -ne 0) {
        throw "npm $Subcommand failed with exit code $exitCode."
    }

    $deprecatedLines = @(
        $npmLines | Where-Object {
            "$_" -match '(?i)npm\s+warn\s+deprecated'
        }
    )

    if ($deprecatedLines.Count -gt 0) {
        throw "npm $Subcommand installed a deprecated package. Resolve the dependency before continuing."
    }
}

Write-Host "=== PackCheck AI Windows bootstrap ===" -ForegroundColor Cyan
Write-Host "Policy: pinned runtime + fail-fast setup + no deprecation warnings." -ForegroundColor DarkGray

foreach ($command in @("node", "npm.cmd")) {
    Assert-CommandAvailable -Command $command
}

$pythonSelection = Resolve-PackCheckPython -RequestedExecutable $PythonExecutable
$Python313 = $pythonSelection.Executable
$pythonVersion = "Python $($pythonSelection.Runtime.Version)"
$nodeVersionText = (& node --version).ToString().Trim()
$npmVersionText = (& npm.cmd --version).ToString().Trim()

Write-Host "Python: $pythonVersion"
Write-Host "         $Python313" -ForegroundColor DarkGray
Write-Host "Node:   $nodeVersionText"
Write-Host "npm:    $npmVersionText"

$nodeMajor = [int](($nodeVersionText.TrimStart('v') -split '\.')[0])
$npmMajor = [int](($npmVersionText -split '\.')[0])

if ($nodeMajor -ne 24) {
    throw "PackCheck is validated for Node.js 24.x LTS. Found: $nodeVersionText"
}

if ($npmMajor -ne 11) {
    throw "PackCheck is validated for npm 11.x. Found: $npmVersionText"
}

Write-Host "`n[1/3] Preparing Python backend (ONNX Runtime; no PaddlePaddle)..." -ForegroundColor Yellow
Push-Location $BackendRoot
try {
    if ($RecreateBackend -and (Test-Path -LiteralPath $VenvRoot)) {
        Write-Host "Removing existing backend virtual environment..."
        Remove-Item -LiteralPath $VenvRoot -Recurse -Force
    }

    # A venv retains the interpreter used to create it. Repair an older/unsupported
    # environment automatically rather than depending on the current PATH order.
    if (Test-Path -LiteralPath $BackendPython -PathType Leaf) {
        $venvRuntime = Get-PythonRuntimeInfo -Executable $BackendPython
        if ($null -eq $venvRuntime) {
            Write-Host "Existing backend virtual environment is not runnable; recreating it." -ForegroundColor Yellow
            Remove-Item -LiteralPath $VenvRoot -Recurse -Force
        }
        elseif ($venvRuntime.Major -ne 3 -or $venvRuntime.Minor -ne 13) {
            Write-Host "Existing backend virtual environment uses Python $($venvRuntime.Version); recreating it with Python $($pythonSelection.Runtime.Version)." -ForegroundColor Yellow
            Remove-Item -LiteralPath $VenvRoot -Recurse -Force
        }
    }

    # Older prototype revisions installed PaddlePaddle. Never reuse that environment
    # for the ONNX-only baseline.
    if (Test-Path -LiteralPath $BackendPython -PathType Leaf) {
        & $BackendPython -c "import importlib.util,sys; sys.exit(23 if importlib.util.find_spec('paddle') else 0)"

        if ($LASTEXITCODE -eq 23) {
            Write-Host "PaddlePaddle-based virtual environment detected; recreating it." -ForegroundColor Yellow
            Remove-Item -LiteralPath $VenvRoot -Recurse -Force
        }
        elseif ($LASTEXITCODE -ne 0) {
            throw "Unable to validate the existing backend virtual environment."
        }
    }

    if (-not (Test-Path -LiteralPath $BackendPython -PathType Leaf)) {
        Invoke-Checked `
            -Command $Python313 `
            -Arguments @("-m", "venv", ".venv") `
            -Description "Create backend virtual environment with Python 3.13"
    }

    Invoke-PipChecked `
        -Arguments @("install", "--upgrade", "pip==26.2.1") `
        -Description "Install pinned pip"

    Invoke-PipChecked `
        -Arguments @("install", "-r", "requirements.txt") `
        -Description "Install backend dependencies"

    Invoke-Checked `
        -Command $BackendPython `
        -Arguments @("-m", "pip", "check") `
        -Description "Check backend dependency consistency"

    Invoke-Checked `
        -Command $BackendPython `
        -Arguments @(
            "-W", "error::DeprecationWarning",
            "-W", "error::FutureWarning",
            "scripts\verify_ocr_runtime.py"
        ) `
        -Description "Verify ONNX Runtime environment"

    Invoke-Checked `
        -Command $BackendPython `
        -Arguments @(
            "-W", "error::DeprecationWarning",
            "-W", "error::FutureWarning",
            "-m", "pytest", "-q"
        ) `
        -Description "Run backend tests"

    if (-not $SkipOcrWarmup) {
        Write-Host "`n[2/3] Downloading/initializing PP-OCRv6 medium ONNX models..." -ForegroundColor Yellow
        Write-Host "Fresh OS detected by policy: no model cache is assumed."

        $env:PADDLE_PDX_MODEL_SOURCE = "BOS"
        $env:PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK = "1"

        Assert-FileExists `
            -Path $SampleLabelPath `
            -Description "OCR warm-up sample image"

        Invoke-Checked `
            -Command $BackendPython `
            -Arguments @(
                "-W", "error::DeprecationWarning",
                "-W", "error::FutureWarning",
                "scripts\verify_ocr_runtime.py",
                "--warmup-image", $SampleLabelPath
            ) `
            -Description "OCR model warm-up"
    }
    else {
        Write-Host "`n[2/3] OCR model warm-up skipped by request." -ForegroundColor Yellow
    }
}
finally {
    Pop-Location
}

Write-Host "`n[3/3] Preparing Next.js frontend..." -ForegroundColor Yellow
Push-Location $FrontendRoot
try {
    if (Test-Path -LiteralPath "package-lock.json" -PathType Leaf) {
        Invoke-NpmInstallChecked -Subcommand "ci"
    }
    else {
        Invoke-NpmInstallChecked -Subcommand "install"
    }

    Invoke-Checked `
        -Command "npm.cmd" `
        -Arguments @("run", "typecheck") `
        -Description "TypeScript typecheck"

    Invoke-Checked `
        -Command "npm.cmd" `
        -Arguments @("run", "lint") `
        -Description "ESLint"

    Invoke-Checked `
        -Command "npm.cmd" `
        -Arguments @("run", "build") `
        -Description "Build Next.js frontend"
}
finally {
    Pop-Location
}

Write-Host "`nSetup complete." -ForegroundColor Green
Write-Host "Python:      $pythonVersion"
Write-Host "OCR runtime: ONNX Runtime / CPUExecutionProvider"
Write-Host "OCR models:  PP-OCRv6 medium detector + recognizer"
Write-Host "PaddlePaddle: not installed / not required"
Write-Host "Warnings:     deprecation/future warnings are treated as failures"
Write-Host "Run from VS Code: Tasks: Run Task -> Dev: Start Backend + Frontend"
Write-Host "Run from PowerShell: .\scripts\run\start-prototype.ps1"
