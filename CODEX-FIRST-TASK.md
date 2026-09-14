# First Codex task

Paste this into Codex after opening the repository root in VS Code:

> Read `AGENTS.md`, `README.md`, `WINDOWS-SETUP.md`, `VERCEL-DEPLOYMENT.md`, `CHANGELOG.md`, and the complete repository before changing anything.
>
> This machine was recently reinstalled. There are no previous project files, virtual environments, or OCR model caches to rely on.
>
> Global environment:
> - Windows x64
> - Python 3.13.15
> - Node.js 24.21.0 LTS
> - npm 11.19.0
>
> Stability is more important than chasing versions. Deprecation warnings must be investigated rather than ignored or suppressed.
>
> Establish the local baseline only:
> 1. Inspect `scripts/setup/bootstrap-windows.ps1`, `backend/requirements.txt`, `backend/app/ocr/paddle_onnx_engine.py`, `frontend/package.json`, and `frontend/eslint.config.mjs`.
> 2. Confirm PaddlePaddle is not a dependency and OCR explicitly uses ONNX Runtime.
> 3. Confirm no source code uses deprecated PaddleOCR APIs such as legacy `ocr()`/angle-classifier parameters or deprecated Next.js lint configuration.
> 4. Run `pwsh -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup\bootstrap-windows.ps1 -RecreateBackend` from the repository root.
> 5. Do not suppress any deprecation/future warning to get setup green. If one occurs, identify the package/API and fix the underlying cause if a stable supported path exists.
> 6. Verify exact pinned OCR package versions and `CPUExecutionProvider`.
> 7. Allow PP-OCRv6 medium ONNX models to download because this OS has no old cache.
> 8. Confirm the canonical sample directory is root `samples/`, with no duplicate package-image fixtures under `backend/tests/fixtures/`.
> 9. Run `pip check`, all backend tests, OCR warm-up on `samples/sample-label.png`, frontend typecheck, ESLint, and production build.
> 10. Review npm output specifically for `npm warn deprecated`. Do not call setup clean if such a warning remains.
> 11. Do not redesign or add features yet.
> 12. Report exact commands, warnings, changes, package versions, ONNX providers, tests, and build results.
