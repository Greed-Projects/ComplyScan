# Changelog

## v0.8.0 — Multi-Image Package Inspection / Cross-View Evidence Fusion

- Consolidated the fully verified v0.7 difficult-text OCR path, including spatial attention, detector-free PP-OCRv6 `TextRecognition`, MRP/unit-rate disambiguation, and consensus recovery of the Maggi seal MRP as `INR 60`.
- Changed package inspection from a single-image assumption to one inspection containing up to six views of the same physical package.
- Added per-image OCR/declaration results with globally namespaced region IDs and explicit source-image provenance.
- Added `app/inspection.py` to fuse structured declarations across front/back/side/seal/bottom views before legal evaluation.
- Repeated matching declarations now retain evidence from all confirming images.
- Complementary consumer-care evidence can be fused across views.
- Conflicting declaration values across images are preserved as explicit conflict metadata and force `Review` instead of silently selecting a passing value.
- Updated the frontend for multiple file selection, package-view thumbnails, cross-view inspection summary, per-image evidence overlays, and combined JSON reporting.
- Added request limits of six images, 10 MB per image, and 40 MB combined.
- Expanded backend automated coverage to 50 tests.
- Hardened Net Quantity, Month/Year and MRP extraction with geometry-aware OCR label/value pairing so nutritional values and barcodes are not promoted solely by OCR serialization order.
- Removed unlabeled gram-value fallback for net quantity; a legal quantity now requires declaration context.
- Added MRP plausibility filtering and same-line text fallback boundaries to prevent barcode-like numbers from being interpreted as retail price.

## v0.7.0 — Computer Vision / Multi-View OCR Ensemble

- Replaced the single targeted enhancement retry with an explicit `Computer Vision → image-variant OCR → evidence fusion` fallback for difficult referenced declarations.
- Added `app/vision/preprocessing.py` so package-region localization and pixel transformations are separated from OCR parsing and Legal Metrology rules.
- Added seal/bottom/top visual target localization with dark-band geometry and edge-energy scoring.
- Added horizontal text-band localization inside candidate regions so faint dot-matrix text occupies a much larger portion of the OCR input.
- Added a bounded OCR image ensemble: full original, full CLAHE, localized line original, CLAHE, inverted CLAHE, gamma-adjusted, inverted gamma, top-hat, inverted top-hat, and adaptive-threshold views.
- Added source-rectangle provenance to every transformed image so OCR polygons are mapped back to the correct coordinates on the original package photograph.
- Fixed reference understanding for real full-page OCR ordering where `MRP ...` and `See under the seal` are returned as separate distant OCR regions.
- Added tolerance for the real fixture OCR spelling `indl.of all taxes` when identifying tax-inclusive MRP reference evidence.
- Added conservative OCR candidate fusion. Multiple preprocessing families may form consensus; weak single-variant or conflicting candidates remain `Review` instead of being guessed.
- Added per-variant OCR diagnostics to API responses and the frontend recovery panel.
- Enhanced `OCR: Verify Referenced MRP Fixture` to print every preprocessing/OCR result and export generated diagnostic images to `backend/.diagnostics/referenced-mrp/`.
- Added Git ignore coverage for local diagnostic outputs.
- Added spatial-attention windows after the first wide seal ensemble still missed the faint left-side MRP text.
- Added detector-free PP-OCRv6 `TextRecognition` for already-localized text-line crops; this proved the end-to-end detector, not the recognizer, was the limiting stage.
- Added MRP candidate disambiguation so `Rs 60 (Rs.0.21 per g)` resolves to MRP `INR 60` instead of the adjacent unit sale price.
- Real Windows runtime verification recovered `INR 60` with six agreeing variants across five preprocessing families.
- Final accepted v0.7 backend automated coverage: 45 tests.

## v0.6.0 — Referenced Declaration / Targeted Seal OCR Recovery

- Added a referenced-declaration recovery stage between primary OCR and Legal Metrology rule evaluation.
- Detects MRP locator wording such as `See under the seal`, including multiline OCR text and common seal/seam/crimp/bottom/top locators.
- Added deterministic visual target selection for long dark seal/crimp bands plus bottom/top region fallbacks.
- Added targeted preprocessing variants for difficult variable printing: upscale, CLAHE/gamma contrast recovery, and a dot-matrix top-hat pass.
- Targeted OCR regions are remapped back to original-image normalized coordinates and tagged with provenance for visual evidence overlays.
- Recovered MRP values are emitted as normal structured facts with currency, amount, tax-inclusive reference evidence, locator and recovery strategy.
- If a valid MRP locator is seen but the value remains unreadable, the rule engine reports unresolved/review evidence rather than falsely declaring MRP absent.
- Added tolerance for common targeted dot-matrix OCR confusions (`R5` → `Rs`, `O` → `0`) only inside the referenced-MRP recovery path.
- Added the supplied low-contrast black-seal packet image as a deterministic region-detection fixture.
- Added `OCR: Verify Referenced MRP Fixture`, an explicit real-model regression task that expects `INR 60` from that image.
- Added frontend recovery diagnostics so inspectors can see whether a reference was resolved, how many targeted OCR attempts ran, and which strategy succeeded.
- Expanded backend automated coverage to 33 tests.

## v0.5.0 — Versioned Legal Rule Profile / Applicability Foundation

- Replaced the flat prototype declaration list with a versioned physical retail-package Legal Metrology rule profile.
- Added stable rule IDs, legal references, requirement text, profile scope metadata and explicit exclusions to API findings.
- Added inspector-supplied package context for imported products, perishable/human-consumption applicability, dimension relevance, package form, alcoholic beverages and tobacco/pan-masala classification.
- Added conditional country-of-origin, best-before/use-by and dimension checks instead of treating them as universally missing or universally optional.
- Added Rule 26(a) small-package scope handling for general packages at or below 10 g / 10 ml while retaining tobacco and pan masala in scope.
- Added MRP validation for Indian-currency evidence and the “inclusive of all taxes” wording.
- Added manufacturer/address and consumer-care completeness review signals.
- Added deterministic Rule 6(11) unit-sale-price basis and arithmetic validation using extracted MRP and net quantity.
- Added not-applicable findings and applicable-rule scoring; non-applicable rules no longer inflate or reduce the score.
- Updated the frontend with a legal-context panel, rule references, profile metadata, N/A states and the corrected unit-sale-price demo.
- Expanded backend coverage to 24 tests.

## v0.4.1 — Windows Multi-Python Bootstrap Hotfix

- Fixed bootstrap behavior on Windows systems with multiple Python versions installed.
- Python 3.13 is now selected explicitly instead of trusting the first `python` command on PATH.
- Discovery prefers the Windows `py -3.13` launcher, then version-specific commands, standard python.org installation locations, and all generic Python commands on PATH.
- Added `-PythonExecutable` for explicit interpreter selection on non-standard installations.
- Existing backend virtual environments created with a non-3.13 interpreter are now detected and recreated automatically.
- Improved setup diagnostics to list discovered Python runtimes when Python 3.13 cannot be found.

## v0.4.0 — Structured Declaration Extraction / Deterministic Rule Boundary

- Split the old regex analyzer into explicit extraction, rule-evaluation, and orchestration layers.
- Added `ExtractedDeclaration` API facts with normalized values, attributes, evidence, confidence, and OCR region IDs.
- Added `prototype-declarations-v1` ruleset metadata to analysis responses.
- MRP parsing now preserves currency and amount separately; `₹`, `Rs.` and `INR` normalize to `INR`.
- MRP values without a captured currency marker are flagged for review instead of silently assuming INR.
- Net quantity and unit-sale-price values now expose structured amount/unit attributes.
- Prevented a unit-sale-price denominator such as `100 g` from being treated as net quantity by the unlabeled fallback.
- Frontend findings now display normalized extracted values and include the ruleset in report metadata.
- Expanded backend automated coverage from 8 to 13 tests.
- Integrated the organized `scripts/common`, `scripts/run`, `scripts/setup`, and `scripts/verify` layout and corrected VS Code tasks/documentation to invoke those scripts.

## v0.3.0 — Stable ONNX Runtime OCR Foundation

- Replaced the v0.2 PaddlePaddle runtime with **ONNX Runtime 1.29.0**.
- Restored the previously validated architecture: PaddleOCR/PaddleX integration with PP-OCRv6 medium models executed through ONNX Runtime on CPU.
- Pinned PaddleOCR 3.7.0, PaddleX 3.7.2, OpenCV 4.10.0.84 and NumPy 2.3.5.
- Removed the old PaddlePaddle compatibility/type alias and fixed the OCR implementation name to `PaddleOcrOnnxEngine`.
- Fixed OCR profile to PP-OCRv6 medium detector + recognizer instead of silently switching between small/medium models.
- Added exact runtime/provider/version diagnostics and explicit verification that PaddlePaddle is absent.
- Added fresh-OS PP-OCRv6 model warm-up; no old cache is assumed.
- Added fail-fast PowerShell handling for native command failures.
- Added `pip check`.
- Promoted Python `DeprecationWarning` and `FutureWarning` to errors in tests, OCR verification and backend development startup.
- Updated frontend linting to modern ESLint flat config; no deprecated `next lint` or legacy `.eslintrc` path.
- Updated ESLint from the unsupported/deprecated 9.x line seen during v0.2 setup to pinned ESLint 10.9.1.
- Added zero-warning ESLint policy, explicit TypeScript typecheck, and production build validation to setup.
- Added exact top-level frontend version pins and npm engine constraints for Node 24/npm 11.
- Added Codex instructions specifically for a clean Windows OS reinstall and no existing OCR cache.

## v0.2.0

- Replaced Tesseract with PaddleOCR spatial OCR evidence.
- Added OCR abstraction, normalized polygons/confidence, declaration-to-region association and frontend evidence overlays.
- v0.2 attempted to use PaddlePaddle directly; that runtime choice is superseded by v0.3.
