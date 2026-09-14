from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Iterable

from .models import ExtractedDeclaration, PackageImageAnalysis


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _decimal(value: str | None) -> Decimal | None:
    if not value:
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def _declaration_identity(item: ExtractedDeclaration) -> tuple[str, ...]:
    """Return a comparison identity that avoids false conflicts from formatting."""
    if item.key == "mrp":
        amount = _decimal(item.attributes.get("amount"))
        currency = item.attributes.get("currency", "")
        if amount is not None:
            return (item.key, currency.upper(), str(amount.normalize()))
    if item.key == "net_quantity":
        amount = _decimal(item.attributes.get("amount"))
        unit = item.attributes.get("unit", "")
        if amount is not None:
            return (item.key, str(amount.normalize()), unit.lower())
    return (item.key, " ".join(item.value.lower().split()))


def _labelled_evidence(item: ExtractedDeclaration) -> str:
    source_file = item.attributes.get("source_file")
    return f"[{source_file}] {item.evidence}" if source_file else item.evidence


def _merge_consumer_care(items: list[ExtractedDeclaration]) -> ExtractedDeclaration:
    best = max(items, key=lambda item: item.confidence)
    attributes = dict(best.attributes)
    for key in ("email", "phone"):
        values = _unique(item.attributes.get(key, "") for item in items)
        if values:
            attributes[key] = values[0]
            if len(values) > 1:
                attributes[f"{key}_candidates"] = " | ".join(values)
    attributes["address_detected"] = str(
        any(item.attributes.get("address_detected") == "true" for item in items)
    ).lower()
    attributes["multi_image_fused"] = "true" if len(items) > 1 else "false"

    values = _unique(item.value for item in items)
    return best.model_copy(
        update={
            "value": " | ".join(values),
            "evidence": " || ".join(_unique(_labelled_evidence(item) for item in items)),
            "confidence": max(item.confidence for item in items),
            "attributes": attributes,
            "region_ids": _unique(region_id for item in items for region_id in item.region_ids),
            "source_image_ids": _unique(image_id for item in items for image_id in item.source_image_ids),
        }
    )


def merge_declaration_groups(
    declaration_groups: Iterable[Iterable[ExtractedDeclaration]],
) -> list[ExtractedDeclaration]:
    """Fuse declaration evidence from one or more views of the same package."""
    groups: dict[str, list[ExtractedDeclaration]] = defaultdict(list)
    for declarations in declaration_groups:
        for declaration in declarations:
            groups[declaration.key].append(declaration)

    merged: list[ExtractedDeclaration] = []
    for key, items in groups.items():
        if key == "consumer_care":
            merged.append(_merge_consumer_care(items))
            continue

        best = max(items, key=lambda item: item.confidence)
        identities = {_declaration_identity(item) for item in items}
        attributes = dict(best.attributes)
        source_image_ids = _unique(image_id for item in items for image_id in item.source_image_ids)
        region_ids = _unique(region_id for item in items for region_id in item.region_ids)
        evidence = " || ".join(_unique(_labelled_evidence(item) for item in items))

        if len(identities) > 1:
            attributes["multi_image_conflict"] = "true"
            attributes["candidate_values"] = " | ".join(_unique(item.value for item in items))
        elif len(items) > 1:
            attributes["multi_image_confirmed"] = "true"

        merged.append(
            best.model_copy(
                update={
                    "evidence": evidence,
                    "confidence": max(item.confidence for item in items),
                    "attributes": attributes,
                    "region_ids": region_ids,
                    "source_image_ids": source_image_ids,
                }
            )
        )

    return merged


def merge_image_declarations(images: Iterable[PackageImageAnalysis]) -> list[ExtractedDeclaration]:
    """Fuse declaration evidence across full per-image analysis results."""
    return merge_declaration_groups(image.declarations for image in images)
