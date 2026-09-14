# PackCheck AI — Codex Project Instructions

## Goal
Build a focused SIH 2026 prototype for AI-assisted Legal Metrology packaged-commodity screening.

## Runtime architecture — do not silently change
- Frontend: Next.js / TypeScript.
- API: Python / FastAPI.
- OCR model family: PaddleOCR PP-OCRv6.
- OCR execution backend: **ONNX Runtime**, CPU-first.
- OCR models: `PP-OCRv6_medium_det` + `PP-OCRv6_medium_rec`.
- Do **not** add PaddlePaddle unless the architecture is deliberately reconsidered.
- Do **not** add Tesseract unless it is a deliberate benchmark/fallback experiment.

## Fresh-machine assumption
This repository is being set up after an OS reinstall. Do not rely on:
- an old `.venv`,
- previous project files,
- an existing PaddleX/PaddleOCR model cache,
- globally installed Python packages.

The expected global baseline is:
- Windows x64
- Python 3.13.15
- Node.js 24.21.0 LTS
- npm 11.19.0

## Pinned OCR baseline
- `paddleocr==3.7.0`
- `paddlex[ocr-core]==3.7.2`
- `onnxruntime==1.29.0`
- `opencv-contrib-python==4.10.0.84`
- `numpy==2.3.5`
- `CPUExecutionProvider`

## Deprecation and stability policy
Deprecation warnings are defects to investigate, not output to ignore.

- Do not introduce deprecated APIs when a supported API is available.
- Do not suppress `DeprecationWarning`/`FutureWarning` merely to make tests pass.
- Backend tests and OCR verification intentionally promote those warnings to errors.
- Do not use deprecated `next lint` or legacy `.eslintrc` configuration.
- Preserve ESLint flat config and `--max-warnings=0`.
- Keep direct runtime/tool dependencies pinned to exact stable versions.
- Do not use beta, RC, canary, nightly, preview, or experimental package releases without an explicit reason and approval.
- Preserve `package-lock.json` once generated; use `npm ci` for subsequent clean installs.
- If a third-party transitive dependency emits a deprecation warning, identify which package/version causes it before deciding on a change.

## Sample image contract
- The canonical prototype/demo image directory is root `samples/`.
- Use `samples/sample-label.png` for OCR warm-up/runtime verification.
- Difficult-image regression samples also live under `samples/`; do not recreate duplicate copies under `backend/tests/fixtures/`.
- Tests, setup scripts, and verification scripts must resolve sample files from the canonical `samples/` directory.
- Do not add experimental or known-failing images to `samples/` for the v0.8 demo baseline.

## Deployment contract
- Vercel hosts the Next.js frontend from `frontend/`.
- The FastAPI + PaddleOCR/ONNX Runtime backend remains a separate Python service.
- Frontend backend routing is configured with `NEXT_PUBLIC_API_URL`.
- Backend CORS deployment origins are configured with `PACKCHECK_ALLOWED_ORIGINS`.
- Preserve local-development defaults while keeping deployment configuration environment-driven.
- Read `VERCEL-DEPLOYMENT.md` before changing deployment topology.

## OCR contract
Keep OCR behind `OcrEngine` and preserve:
- recognized text,
- confidence,
- normalized polygon coordinates,
- source-image dimensions,
- engine/model provenance.

Legal/compliance code must not depend directly on PaddleOCR/PaddleX result objects.

## Compliance behavior
- Deterministic rules produce the prototype screening result.
- OCR/AI provides evidence; it does not itself make legal determinations.
- Never claim millimetre font-size compliance from pixels without scale/calibration.
- Keep the prototype disclaimer visible.

## Validation before completion
Backend:
1. `backend\.venv\Scripts\python.exe -m pip check`
2. `backend\.venv\Scripts\python.exe scripts\verify_ocr_runtime.py`
3. `backend\.venv\Scripts\python.exe -W error::DeprecationWarning -W error::FutureWarning -m pytest -q`
4. For OCR changes: warm-up/test `samples/sample-label.png`.

Frontend:
1. `npm run typecheck`
2. `npm run lint`
3. `npm run build`

Report exact results. Never claim a command passed if it was not run successfully.

## Scope
Prioritize this reliable path:

`one or more package images -> per-image CV/OCR evidence -> cross-image declaration fusion -> deterministic screening -> per-image visual evidence/report`

Preserve the verified difficult-text fallback and multi-image provenance. Do not broaden into unrelated platform features until the physical-package inspection path is stable and measured on real package images.
