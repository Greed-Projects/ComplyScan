from __future__ import annotations

import argparse
import re
import shutil
import sys
import warnings
from pathlib import Path


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify referenced MRP recovery on a difficult package image and "
            "show end-to-end and detector-free OCR recovery results."
        )
    )
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--expected-amount", default="60")
    parser.add_argument("--diagnostics-dir", type=Path)
    args = parser.parse_args()

    warnings.simplefilter("error", DeprecationWarning)
    warnings.simplefilter("error", FutureWarning)

    image_path = args.image.resolve()
    if not image_path.is_file():
        print(f"ERROR: fixture image does not exist: {image_path}")
        return 2

    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from app.extraction import extract_declarations
    from app.ocr.paddle_onnx_engine import PaddleOcrOnnxEngine
    from app.ocr.targeted_recovery import (
        detect_reference_hints,
        recover_referenced_declarations,
    )
    from app.vision.preprocessing import find_target_crops, preprocessing_variants

    raw = image_path.read_bytes()
    engine = PaddleOcrOnnxEngine()

    print("=== Referenced MRP runtime verification ===")
    print(f"Image:                  {image_path.name}")
    print(f"Expected MRP:           INR {args.expected_amount}")

    if args.diagnostics_dir:
        diagnostics = args.diagnostics_dir.resolve()
        if diagnostics.exists():
            shutil.rmtree(diagnostics)
        diagnostics.mkdir(parents=True, exist_ok=True)
        variant_index = 1
        crops = find_target_crops(raw, "seal")[:2]
        for crop_index, crop in enumerate(crops, start=1):
            crop_meta = (
                f"crop={crop.label} x={crop.x} y={crop.y} "
                f"w={crop.width} h={crop.height} score={crop.score:.4f}"
            )
            (diagnostics / f"crop-{crop_index:02d}.txt").write_text(
                crop_meta + "\n",
                encoding="utf-8",
            )
            for variant in preprocessing_variants(raw, crop):
                filename = (
                    f"{variant_index:02d}_"
                    f"{_safe_name(crop.label)}__{_safe_name(variant.name)}.png"
                )
                (diagnostics / filename).write_bytes(variant.raw)
                variant_index += 1
        print(f"Diagnostic variants:    {diagnostics}")

    print("Running primary OCR...")
    primary = engine.extract(raw)
    direct = extract_declarations(primary.text)
    direct_mrp = next((item for item in direct if item.key == "mrp"), None)
    hints = detect_reference_hints(primary.text)

    print(f"Primary OCR regions:    {len(primary.regions)}")
    print(f"Reference hints:        {len(hints)}")
    for hint in hints:
        print(
            f"Reference:              key={hint.declaration_key}, locator={hint.locator}, "
            f"tax-inclusive={hint.tax_inclusive_phrase}"
        )
        print(f"Reference evidence:     {hint.evidence}")

    if direct_mrp and direct_mrp.attributes.get("amount") == args.expected_amount:
        print(f"Recovered path:         primary OCR ({direct_mrp.value})")
        print("Referenced MRP fixture: PASS")
        return 0

    print("Direct MRP unresolved; running localized OCR recovery pipeline...")
    outcome = recover_referenced_declarations(raw, primary.text, direct, engine, primary.regions)
    recovered_mrp = next(
        (item for item in outcome.declarations if item.key == "mrp"),
        None,
    )

    expected_candidate_seen = False
    for trace in outcome.traces:
        print(
            f"Recovery trace:         key={trace.declaration_key}, locator={trace.locator}, "
            f"attempted={trace.attempted}, resolved={trace.resolved}, attempts={trace.attempts}"
        )
        if trace.strategy:
            print(f"Recovery strategy:      {trace.strategy}")
        print("\n--- Localized OCR recovery attempts ---")
        if not trace.variants:
            print("(no variants executed)")
        for index, variant in enumerate(trace.variants, start=1):
            parsed = variant.parsed_value or "-"
            if parsed == f"INR {args.expected_amount}":
                expected_candidate_seen = True
            compact = " ".join((variant.text or "<no text>").split())[:220]
            print(
                f"{index:02d}. {variant.crop} / {variant.variant} "
                f"[{variant.family}] conf={variant.confidence:.3f} parsed={parsed}"
            )
            print(f"    OCR: {compact}")
        print("--- End recovery attempts ---\n")
        if trace.recovered_text:
            compact = " ".join(trace.recovered_text.split())[:400]
            print(f"Best diagnostic OCR:    {compact}")
        print(f"Decision:               {trace.message}")

    if recovered_mrp and recovered_mrp.attributes.get("amount") == args.expected_amount:
        print(f"Recovered MRP:          {recovered_mrp.value}")
        print(f"Evidence:               {recovered_mrp.evidence}")
        print(
            "Consensus:              "
            f"{recovered_mrp.attributes.get('ensemble_votes', '?')} variants / "
            f"{recovered_mrp.attributes.get('ensemble_families', '?')} families"
        )
        print("Referenced MRP fixture: PASS")
        return 0

    if expected_candidate_seen:
        print(
            "ERROR: INR amount was seen by at least one image variant, but the "
            "ensemble did not reach the conservative consensus threshold."
        )
    else:
        print("ERROR: expected INR amount was not recognized by any localized OCR recovery attempt.")

    print("\n--- Primary OCR text (diagnostic) ---")
    print(primary.text[:5000])
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
