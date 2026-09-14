from __future__ import annotations

from typing import Iterable

from .extraction import extract_declarations
from .models import ComplianceSummary, DeclarationCheck, ExtractedDeclaration, OcrRegion, PackageContext
from .rules import evaluate_declarations


def _merge_declarations(
    primary: Iterable[ExtractedDeclaration],
    supplemental: Iterable[ExtractedDeclaration],
) -> list[ExtractedDeclaration]:
    merged = list(primary)
    index_by_key = {item.key: index for index, item in enumerate(merged)}

    for item in supplemental:
        existing_index = index_by_key.get(item.key)
        if existing_index is None:
            index_by_key[item.key] = len(merged)
            merged.append(item)
            continue

        # Prefer the stronger fact when two extraction paths resolve the same
        # declaration. In normal image flow targeted recovery only runs when the
        # direct value is absent, but this makes the merge contract robust.
        if item.confidence > merged[existing_index].confidence:
            merged[existing_index] = item

    return merged


def analyze_text_with_declarations(
    raw_text: str,
    regions: Iterable[OcrRegion] = (),
    context: PackageContext | None = None,
    supplemental_declarations: Iterable[ExtractedDeclaration] = (),
) -> tuple[list[ExtractedDeclaration], list[DeclarationCheck], ComplianceSummary]:
    region_list = list(regions)
    primary = extract_declarations(raw_text, region_list)
    declarations = _merge_declarations(primary, supplemental_declarations)
    checks, summary = evaluate_declarations(raw_text, declarations, context)
    return declarations, checks, summary


def analyze_text(
    raw_text: str,
    regions: Iterable[OcrRegion] = (),
    context: PackageContext | None = None,
) -> tuple[list[DeclarationCheck], ComplianceSummary]:
    """Convenience entry point for text-focused callers and tests."""
    _, checks, summary = analyze_text_with_declarations(raw_text, regions, context)
    return checks, summary
