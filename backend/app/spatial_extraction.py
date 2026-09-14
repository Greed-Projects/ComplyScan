from __future__ import annotations

import math
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterable

from .models import OcrRegion


@dataclass(frozen=True, slots=True)
class SpatialFieldCandidate:
    value: str
    evidence: str
    confidence: float
    attributes: dict[str, str]
    region_ids: tuple[str, ...]


def _compact_label(value: str) -> str:
    return re.sub(r"[^a-z0-9₹]+", "", value.lower())


def _compact_evidence(*values: str) -> str:
    return " | ".join(value.strip() for value in values if value.strip())[:220]


def _center(region: OcrRegion) -> tuple[float, float]:
    x, y, width, height = region.bbox
    return x + width / 2.0, y + height / 2.0


def _distance(left: OcrRegion, right: OcrRegion) -> float:
    left_x, left_y = _center(left)
    right_x, right_y = _center(right)
    return math.hypot(left_x - right_x, left_y - right_y)


def _is_aligned(left: OcrRegion, right: OcrRegion) -> bool:
    left_x, left_y, left_width, left_height = left.bbox
    right_x, right_y, right_width, right_height = right.bbox

    left_cx = left_x + left_width / 2.0
    left_cy = left_y + left_height / 2.0
    right_cx = right_x + right_width / 2.0
    right_cy = right_y + right_height / 2.0

    same_row = abs(left_cy - right_cy) <= max(
        0.035,
        1.5 * max(left_height, right_height),
    )
    same_column = abs(left_cx - right_cx) <= max(
        0.035,
        1.5 * max(left_width, right_width),
    )
    return same_row or same_column


def _pair_score(
    anchor: OcrRegion,
    value: OcrRegion,
    anchor_strength: float,
    max_distance: float,
) -> float | None:
    distance = _distance(anchor, value)
    if distance > max_distance or not _is_aligned(anchor, value):
        return None

    proximity = 1.0 - (distance / max_distance)
    return (
        anchor_strength * 2.0
        + anchor.confidence * 0.35
        + value.confidence * 0.45
        + proximity * 1.6
        + 0.35
    )


def _best_pair(
    anchors: list[tuple[OcrRegion, float]],
    values: list[tuple[OcrRegion, object]],
    max_distance: float,
) -> tuple[OcrRegion, OcrRegion, object] | None:
    best: tuple[float, OcrRegion, OcrRegion, object] | None = None
    for anchor, strength in anchors:
        for value_region, payload in values:
            if anchor.id == value_region.id:
                continue
            score = _pair_score(anchor, value_region, strength, max_distance)
            if score is None:
                continue
            if best is None or score > best[0]:
                best = (score, anchor, value_region, payload)

    if best is None:
        return None
    return best[1], best[2], best[3]


_QUANTITY_RE = re.compile(
    r"^\s*(?P<amount>\d{1,6}(?:\.\d{1,3})?)\s*"
    r"(?P<unit>kg|mg|g|ml|cl|l|pcs?|pieces?|n)\.?\s*$",
    flags=re.IGNORECASE,
)


def _net_anchor_strength(text: str) -> float:
    compact = _compact_label(text)
    if any(
        token in compact
        for token in ("netquantity", "netqty", "netweight", "netwt")
    ):
        return 1.0

    # Tolerate the observed PP-OCRv6 reading "Ne W" for "Net Wt." without
    # treating arbitrary text containing "new" as a declaration label.
    if compact in {"new", "newt", "netw", "netwt"}:
        return 0.82

    return 0.0


def _parse_quantity(text: str) -> tuple[str, str] | None:
    match = _QUANTITY_RE.fullmatch(text)
    if not match:
        return None

    amount = match.group("amount")
    try:
        if Decimal(amount) <= 0:
            return None
    except InvalidOperation:
        return None

    unit = match.group("unit").lower()
    if unit in {"pc", "pcs", "piece", "pieces", "n"}:
        unit = "pc"
    return amount, unit


def _extract_net_quantity(regions: list[OcrRegion]) -> SpatialFieldCandidate | None:
    anchors = [
        (region, strength)
        for region in regions
        if (strength := _net_anchor_strength(region.text)) > 0
    ]
    values: list[tuple[OcrRegion, object]] = []
    for region in regions:
        parsed = _parse_quantity(region.text)
        if parsed:
            values.append((region, parsed))

    pair = _best_pair(anchors, values, max_distance=0.16)
    if pair is None:
        return None

    anchor, value_region, payload = pair
    amount, unit = payload
    confidence = min(
        0.98,
        0.82 + 0.08 * anchor.confidence + 0.08 * value_region.confidence,
    )
    return SpatialFieldCandidate(
        value=f"{amount} {unit}",
        evidence=_compact_evidence(anchor.text, value_region.text),
        confidence=confidence,
        attributes={
            "amount": amount,
            "unit": unit,
            "extraction_strategy": "spatial_label_value",
        },
        region_ids=(anchor.id, value_region.id),
    )


_MONTH_NAMES = {
    "jan": "01",
    "january": "01",
    "feb": "02",
    "february": "02",
    "mar": "03",
    "march": "03",
    "apr": "04",
    "april": "04",
    "may": "05",
    "jun": "06",
    "june": "06",
    "jul": "07",
    "july": "07",
    "aug": "08",
    "august": "08",
    "sep": "09",
    "sept": "09",
    "september": "09",
    "oct": "10",
    "october": "10",
    "nov": "11",
    "november": "11",
    "dec": "12",
    "december": "12",
}

_MONTH_PATTERN = "|".join(sorted(_MONTH_NAMES, key=len, reverse=True))
_NAMED_MONTH_YEAR_RE = re.compile(
    rf"^\s*(?P<month>{_MONTH_PATTERN})\s*[/\-. ]+\s*"
    r"(?P<year>(?:20)?\d{2})\s*$",
    flags=re.IGNORECASE,
)
_NUMERIC_MONTH_YEAR_RE = re.compile(
    r"^\s*(?P<month>0?[1-9]|1[0-2])\s*[/\-.]\s*"
    r"(?P<year>(?:20)?\d{2})\s*$",
    flags=re.IGNORECASE,
)


def _month_year_anchor_strength(text: str) -> float:
    compact = _compact_label(text)
    strong = (
        "mthofpack",
        "monthofpack",
        "monthofpacking",
        "packingdate",
        "packedon",
        "dateofpacking",
        "mfgdate",
        "mfddate",
        "dateofmanufacture",
        "dateofmanufacturing",
    )
    if any(token in compact for token in strong):
        return 1.0
    if compact in {"mfd", "mfg", "packed", "packing"}:
        return 0.86
    return 0.0


def _parse_month_year(text: str) -> tuple[str, str] | None:
    numeric = _NUMERIC_MONTH_YEAR_RE.fullmatch(text)
    if numeric:
        month = numeric.group("month").zfill(2)
        year = numeric.group("year")
        if len(year) == 2:
            year = f"20{year}"
        return month, year

    named = _NAMED_MONTH_YEAR_RE.fullmatch(text)
    if named:
        month = _MONTH_NAMES[named.group("month").lower()]
        year = named.group("year")
        if len(year) == 2:
            year = f"20{year}"
        return month, year
    return None


def _extract_month_year(regions: list[OcrRegion]) -> SpatialFieldCandidate | None:
    anchors = [
        (region, strength)
        for region in regions
        if (strength := _month_year_anchor_strength(region.text)) > 0
    ]
    values: list[tuple[OcrRegion, object]] = []
    for region in regions:
        parsed = _parse_month_year(region.text)
        if parsed:
            values.append((region, parsed))

    pair = _best_pair(anchors, values, max_distance=0.18)
    if pair is None:
        return None

    anchor, value_region, payload = pair
    month, year = payload
    confidence = min(
        0.98,
        0.80 + 0.08 * anchor.confidence + 0.09 * value_region.confidence,
    )
    return SpatialFieldCandidate(
        value=f"{month}/{year}",
        evidence=_compact_evidence(anchor.text, value_region.text),
        confidence=confidence,
        attributes={
            "month": month,
            "year": year,
            "extraction_strategy": "spatial_label_value",
        },
        region_ids=(anchor.id, value_region.id),
    )


_MRP_VALUE_RE = re.compile(
    r"^\s*(?P<currency>₹|rs\.?|inr)?\s*[:\-]?\s*"
    r"(?P<amount>\d{1,7}(?:\.\d{1,2})?)\s*(?:/\-)?\s*$",
    flags=re.IGNORECASE,
)


def _mrp_anchor_strength(text: str) -> float:
    compact = _compact_label(text)
    if compact.startswith("mrp") or "maximumretailprice" in compact:
        return 1.0
    return 0.0


def _currency_code(token: str | None) -> str | None:
    if not token:
        return None
    normalized = token.strip().lower().replace(".", "")
    if token == "₹" or normalized in {"rs", "inr"}:
        return "INR"
    return None


def _currency_from_anchor(text: str) -> str | None:
    if "₹" in text:
        return "INR"
    compact = _compact_label(text)
    if compact.endswith("rs") or "inr" in compact:
        return "INR"
    return None


def _parse_mrp_value(text: str) -> tuple[str, str | None] | None:
    match = _MRP_VALUE_RE.fullmatch(text)
    if not match:
        return None

    amount = match.group("amount")
    integer_digits = amount.split(".", 1)[0].lstrip("0") or "0"
    if len(integer_digits) > 7:
        return None

    try:
        numeric = Decimal(amount)
    except InvalidOperation:
        return None
    if numeric <= 0:
        return None

    return amount, _currency_code(match.group("currency"))


def _nearby_tax_phrase(anchor: OcrRegion, regions: list[OcrRegion]) -> bool:
    for region in regions:
        if _distance(anchor, region) > 0.22:
            continue
        compact = _compact_label(region.text)
        if "inclusiveofalltaxes" in compact or "inclofalltaxes" in compact:
            return True
    return False


def _extract_mrp(regions: list[OcrRegion]) -> SpatialFieldCandidate | None:
    anchors = [
        (region, strength)
        for region in regions
        if (strength := _mrp_anchor_strength(region.text)) > 0
    ]
    values: list[tuple[OcrRegion, object]] = []
    for region in regions:
        parsed = _parse_mrp_value(region.text)
        if parsed:
            values.append((region, parsed))

    pair = _best_pair(anchors, values, max_distance=0.16)
    if pair is None:
        return None

    anchor, value_region, payload = pair
    amount, value_currency = payload
    currency = value_currency or _currency_from_anchor(anchor.text)
    tax_phrase = _nearby_tax_phrase(anchor, regions)

    attributes = {
        "amount": amount,
        "tax_inclusive_phrase": str(tax_phrase).lower(),
        "extraction_strategy": "spatial_label_value",
    }
    if currency:
        attributes["currency"] = currency

    confidence = min(
        0.98,
        (0.84 if currency else 0.76)
        + 0.06 * anchor.confidence
        + 0.07 * value_region.confidence,
    )
    return SpatialFieldCandidate(
        value=f"{currency} {amount}" if currency else amount,
        evidence=_compact_evidence(anchor.text, value_region.text),
        confidence=confidence,
        attributes=attributes,
        region_ids=(anchor.id, value_region.id),
    )


def extract_spatial_fields(
    regions: Iterable[OcrRegion],
) -> dict[str, SpatialFieldCandidate]:
    region_list = [region for region in regions if region.text.strip()]
    if not region_list:
        return {}

    result: dict[str, SpatialFieldCandidate] = {}
    for key, extractor in (
        ("net_quantity", _extract_net_quantity),
        ("month_year", _extract_month_year),
        ("mrp", _extract_mrp),
    ):
        candidate = extractor(region_list)
        if candidate is not None:
            result[key] = candidate
    return result
