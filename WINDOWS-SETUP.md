# Windows Setup — PackCheck AI v0.8

## Prerequisites

- Windows x64
- Python 3.13.x installed (it does **not** need to be the first `python` on `PATH`)
- Node.js 24.x LTS on `PATH`
- npm 11.x
- PowerShell 7 (`pwsh.exe`)

## Setup / rebuild

From the repository root:

```powershell
pwsh -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup\bootstrap-windows.ps1
```

Recreate the backend virtual environment when needed:

```powershell
pwsh -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup\bootstrap-windows.ps1 -RecreateBackend
```

The bootstrap discovers Python 3.13 independently of PATH ordering. It prefers `py -3.13`, then version-specific commands, standard python.org install locations, and finally all generic `python` commands on PATH. If an existing `.venv` was created with another Python version, it is recreated automatically with 3.13.

For a non-standard installation, select the interpreter explicitly:

```powershell
pwsh -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup\bootstrap-windows.ps1 -PythonExecutable "C:\Path\To\Python313\python.exe"
```

The bootstrap script installs the pinned backend dependencies, verifies the ONNX Runtime CPU provider, runs tests, warms the PP-OCRv6 medium models, installs the locked frontend dependencies, and runs TypeScript, ESLint, and the Next.js production build.

## Run

VS Code:

```text
Terminal → Run Task → Dev: Start Backend + Frontend
```

PowerShell:

```powershell
pwsh -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\scripts\run\start-prototype.ps1
```

## Verify

VS Code:

```text
Terminal → Run Task → Verify: All
```

PowerShell:

```powershell
pwsh -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify\verify-all.ps1
```


## Difficult referenced-MRP OCR regression

The normal `Verify: All` task remains the fast/default contract. To exercise the supplied low-contrast black-seal image with the real PP-OCRv6 runtime, run:

```text
Terminal → Run Task → OCR: Verify Referenced MRP Fixture
```

The check runs full-image OCR first and, when needed, the computer-vision / multi-view OCR ensemble. It prints every variant OCR result and exports the generated diagnostic images to `backend/.diagnostics/referenced-mrp/`. It passes only when the fixture resolves to `INR 60` through the conservative fusion logic.
