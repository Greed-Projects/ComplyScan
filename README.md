# PackCheck AI — SIH 2026 PS 26034 Prototype v0.8

A focused working prototype for AI-assisted screening of packaged-commodity labels under India’s Legal Metrology (Packaged Commodities) Rules framework.

## Stable runtime baseline

The verified OCR runtime remains **PaddleOCR models through ONNX Runtime**, CPU-first:

- CPython 3.13.x on Windows x64; other Python versions may coexist
- PaddleOCR 3.7.0
- PaddleX 3.7.2
- ONNX Runtime 1.29.0
- OpenCV 4.10.0.84
- NumPy 2.3.5
- PP-OCRv6 medium detector + recognizer
- `CPUExecutionProvider`

**PaddlePaddle and Tesseract are not required.**

## v0.8 multi-image package inspection

A physical package is no longer assumed to fit in one photograph. The API and UI accept up to six views of the same package and produce one combined inspection.

```text
front / back / side / seal / bottom images
                  ↓
     OCR each image independently
                  ↓
       per-image declarations
                  ↓
   cross-image evidence fusion
      ├── repeated matching facts reinforce provenance
      ├── complementary facts are combined
      └── conflicting values become Review, never silent pass
                  ↓
    one versioned legal evaluation
                  ↓
 combined findings + per-image visual evidence
```

Every OCR region is namespaced to its source image. Aggregated declarations retain the source image IDs and original evidence so an inspector can switch between views and see where a finding came from.

### Difficult-text OCR architecture retained from the verified v0.7 baseline

The supplied Maggi packet is the first difficult-image regression fixture. Normal full-page OCR sees the MRP locator but misses the faint dot-matrix price on the glossy black seal. The accepted recovery path is:

```text
primary full-image OCR
        ↓
reference understanding (MRP → see under seal)
        ↓
computer-vision target localization
        ↓
text-line / spatial-attention crops
        ↓
multiple image representations
        ├── original / upscaled
        ├── CLAHE local contrast
        ├── inverted polarity
        ├── gamma correction
        ├── dot-matrix top-hat
        └── adaptive threshold
        ↓
normal OCR attempt
        ↓ if detector still misses the text
PP-OCRv6 recognizer directly on localized text-line images
        ↓
candidate disambiguation + multi-family consensus
        ↓
structured declaration + original-image provenance
```

On the real Windows runtime this path recovers the seal MRP as `INR 60` while distinguishing it from the adjacent unit-sale-price text `Rs.0.21 per g`.

The active legal profile is:

```text
india-lmpc-retail-package-2026-05-29-v1
```

It is a **physical retail-package screening profile**. Conditional legal facts are supplied explicitly by the inspector/UI rather than guessed from OCR.

### Context-aware rules currently included

- Manufacturer / packer / importer identity and address evidence — Rule 6(1)(a)
- Country of origin / manufacture / assembly for imported products — Rule 6(1)(aa)
- Common / generic commodity name — Rule 6(1)(b)
- Net quantity — Rule 6(1)(c)
- Month & year of manufacture / packing / import — Rule 6(1)(d)
- Best-before / use-by when applicable — Rule 6(1)(da)
- MRP with Indian-currency and “inclusive of all taxes” evidence — Rule 6(1)(e)
- Dimensions when relevant — Rule 6(1)(f)
- Consumer-care contact evidence — Rule 6(2)
- Unit sale price applicability, prescribed basis and arithmetic — Rule 6(11)
- General ≤10 g / ≤10 ml small-package exemption handling under Rule 26(a), while keeping tobacco and pan masala inside the profile

## Important scope boundary

The result is a screening aid, **not a legal determination or enforcement decision**.

The current physical-package profile intentionally excludes:

- physical font/numeral height calibration under Rules 7-9
- principal display panel geometry
- e-commerce listing-only obligations
- dedicated food/FSSAI interaction logic
- dedicated medical-device rules
- electronic-product QR-code substitution logic
- drugs/cosmetics and other specialized product regimes
- physical net-quantity measurement/testing
- inspector case management, evidence signing and audit trail

## Architecture

```text
Next.js 16 UI
    |
    | multipart upload: 1-6 images + package context
    v
FastAPI / Python 3.13
    |
    +-- OcrEngine contract
    |      +-- PaddleOcrOnnxEngine
    |              +-- PP-OCRv6 medium detection + recognition
    |              +-- detector-free TextRecognition for localized difficult text
    |
    +-- app/vision/preprocessing.py
    |      +-- target-region localization
    |      +-- text-band / attention crops
    |      +-- original / CLAHE / inverted / gamma / top-hat / threshold views
    |
    +-- app/ocr/targeted_recovery.py
    |      +-- referenced-declaration understanding
    |      +-- bounded multi-view OCR
    |      +-- direct recognition fallback
    |      +-- MRP/unit-price candidate disambiguation
    |      +-- consensus and coordinate provenance
    |
    +-- app/extraction.py
    |      +-- declaration-specific structured facts
    |
    +-- app/inspection.py
    |      +-- cross-image fact fusion
    |      +-- repeated-evidence confirmation
    |      +-- conflict preservation / Review metadata
    |
    +-- app/legal_profiles.py + app/rules.py
    |      +-- versioned applicability and deterministic validation
    |
    v
Combined explainable response + per-image overlays + JSON report
```

## Stability / deprecation policy

- Python `DeprecationWarning` and `FutureWarning` are treated as errors during tests, OCR initialization, and backend development startup.
- Frontend packages are pinned to exact versions.
- ESLint uses flat config and runs with `--max-warnings=0`.
- Setup is fail-fast and performs `pip check`, TypeScript typecheck, ESLint, and a production Next.js build before reporting success.
- Once `package-lock.json` exists, subsequent setup runs use `npm ci`.
- The Windows bootstrap explicitly discovers Python 3.13 instead of trusting whichever `python` happens to come first on `PATH`.

## Fresh Windows prerequisites

```text
Python 3.13.x (other installed Python versions are fine)
Node.js 24.x LTS
npm 11.x
PowerShell 7 (`pwsh.exe`)
```

## Project scripts

```text
scripts/
├── common/dev-common.ps1
├── run/
│   ├── run-backend.ps1
│   ├── run-frontend.ps1
│   └── start-prototype.ps1
├── setup/bootstrap-windows.ps1
└── verify/
    ├── verify-all.ps1
    ├── verify-backend.ps1
    ├── verify-frontend.ps1
    └── verify-referenced-mrp.ps1
```

`.vscode/tasks.json` invokes these scripts and does not duplicate their command logic.

## Setup

```powershell
pwsh -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup\bootstrap-windows.ps1
```

## Start

```text
Terminal → Run Task → Dev: Start Backend + Frontend
```

Then open:

- frontend: `http://localhost:3000`
- FastAPI docs: `http://localhost:8000/docs`

## Verification

Full regression contract:

```text
Terminal → Run Task → Verify: All
```

The difficult seal regression is intentionally separate because it executes the real OCR recovery ensemble:

```text
Terminal → Run Task → OCR: Verify Referenced MRP Fixture
```

That check passes only when the supplied fixture resolves to `INR 60` and exports local diagnostics under `backend/.diagnostics/referenced-mrp/`.
