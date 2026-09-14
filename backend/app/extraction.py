from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Iterable

from .models import ExtractedDeclaration, OcrRegion
from .spatial_extraction import extract_spatial_fields


@dataclass(frozen=True, slots=True)
class ExtractionCandidate:
    value: str
    evidence: str
    confidence: float
    attributes: dict[str, str]


Extractor = Callable[[str], ExtractionCandidate | None]


def normalize_ocr_text(text: str) -> str:
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _compact_evidence(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()[:220]


def _line_evidence(text: str, start: int) -> str:
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", start)
    if line_end < 0:
        line_end = len(text)
    return _compact_evidence(text[line_start:line_end])


def _key_text(value: str) -> str:
    return re.sub(r"[^a-z0-9₹]+", " ", value.lower()).strip()


def matching_region_ids(evidence: str | None, regions: Iterable[OcrRegion]) -> list[str]:
    if not evidence:
        return []

    evidence_key = _key_text(evidence)
    evidence_tokens = set(evidence_key.split())
    matches: list[str] = []

    for region in regions:
        region_key = _key_text(region.text)
        if not region_key:
            continue
        region_tokens = set(region_key.split())
        overlap = len(evidence_tokens & region_tokens) / max(1, len(region_tokens))
        if region_key in evidence_key or evidence_key in region_key or overlap >= 0.60:
            matches.append(region.id)

    return matches


def _currency_code(token: str | None) -> str | None:
    if not token:
        return None
    normalized = token.strip().lower().replace(".", "")
    if token == "₹" or normalized in {"rs", "inr"}:
        return "INR"
    return None


def _looks_like_address(value: str) -> bool:
    lowered = value.lower()
    address_terms = (
        "road",
        "rd",
        "street",
        "st",
        "sector",
        "phase",
        "industrial",
        "nagar",
        "colony",
        "district",
        "dist",
        "india",
    )
    return bool(re.search(r"\b\d{6}\b", value)) or value.count(",") >= 2 or any(
        re.search(rf"\b{re.escape(term)}\b", lowered) for term in address_terms
    )


def _extract_manufacturer(text: str) -> ExtractionCandidate | None:
    patterns = (
        r"(?P<role>manufactured|mfd|packed|marketed|imported)\s+by\s*[:\-]?\s*(?P<value>[^\n]{4,})",
        r"(?P<role>manufacturer|packer|importer)\s*[:\-]?\s*(?P<value>[^\n]{4,})",
    )
    for index, pattern in enumerate(patterns):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            value = match.group("value").strip()
            role = match.group("role").lower()
            return ExtractionCandidate(
                value=value,
                evidence=_line_evidence(text, match.start()),
                confidence=0.92 if index == 0 else 0.86,
                attributes={
                    "role": role,
                    "address_detected": str(_looks_like_address(value)).lower(),
                },
            )
    return None


def _extract_country_origin(text: str) -> ExtractionCandidate | None:
    patterns = (
        r"(?:country\s+of\s+(?:origin|manufacture|assembly)|origin)\s*[:\-]?\s*(?P<value>[A-Za-z][A-Za-z .'-]{1,48})",
        r"(?:made|manufactured|assembled)\s+in\s+(?P<value>[A-Za-z][A-Za-z .'-]{1,48})",
    )
    for index, pattern in enumerate(patterns):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            value = match.group("value").strip(" .,-")
            return ExtractionCandidate(
                value=value,
                evidence=_line_evidence(text, match.start()),
                confidence=0.95 if index == 0 else 0.90,
                attributes={"country": value},
            )
    return None


def _extract_commodity_name(text: str) -> ExtractionCandidate | None:
    match = re.search(
        r"(?:product|commodity|generic)\s+name\s*[:\-]?\s*(?P<value>[^\n]{3,})",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    value = match.group("value").strip()
    return ExtractionCandidate(
        value=value,
        evidence=_line_evidence(text, match.start()),
        confidence=0.92,
        attributes={},
    )


def _extract_net_quantity(text: str) -> ExtractionCandidate | None:
    patterns = (
        r"(?:net\s*(?:qty|quantity|wt|weight)|contents?)\s*[:\-]?\s*(?P<amount>\d+(?:\.\d+)?)\s*(?P<unit>kg|g|mg|l|ml|cl|pcs?|pieces?|n)\b",
    )
    for index, pattern in enumerate(patterns):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            amount = match.group("amount")
            unit = match.group("unit")
            normalized_unit = unit.lower()
            if normalized_unit in {"pc", "pcs", "piece", "pieces", "n"}:
                normalized_unit = "pc"
            return ExtractionCandidate(
                value=f"{amount} {normalized_unit}",
                evidence=_line_evidence(text, match.start()),
                confidence=0.94,
                attributes={"amount": amount, "unit": normalized_unit},
            )
    return None


def _mrp_attributes(text: str, match: re.Match[str], amount: str, currency: str | None) -> dict[str, str]:
    evidence = _line_evidence(text, match.start())
    tax_phrase = bool(
        re.search(
            r"(?:inclusive\s+of\s+all\s+taxes|incl\.?\s+of\s+all\s+taxes)",
            evidence,
            flags=re.IGNORECASE,
        )
    )
    attributes = {
        "amount": amount,
        "tax_inclusive_phrase": str(tax_phrase).lower(),
    }
    if currency:
        attributes["currency"] = currency
    return attributes


def _extract_mrp(text: str) -> ExtractionCandidate | None:
    currency_patterns = (
        r"(?:\bmrp\b|m\.?r\.?p\.?)[ \t]*(?::|-)?[ \t]*(?P<currency>₹|rs\.?|inr)[ \t]*(?P<amount>\d{1,7}(?:\.\d{1,2})?)",
        r"maximum\s+retail\s+price[ \t]*(?::|-)?[ \t]*(?P<currency>₹|rs\.?|inr)[ \t]*(?P<amount>\d{1,7}(?:\.\d{1,2})?)",
    )
    for pattern in currency_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            amount = match.group("amount")
            currency = _currency_code(match.group("currency"))
            if not currency:
                continue
            return ExtractionCandidate(
                value=f"{currency} {amount}",
                evidence=_line_evidence(text, match.start()),
                confidence=0.95,
                attributes=_mrp_attributes(text, match, amount, currency),
            )

    fallback_patterns = (
        r"(?:\bmrp\b|m\.?r\.?p\.?)[ \t]*(?::|-)?[ \t]*(?P<amount>\d{1,7}(?:\.\d{1,2})?)",
        r"maximum\s+retail\s+price[ \t]*(?::|-)?[ \t]*(?P<amount>\d{1,7}(?:\.\d{1,2})?)",
    )
    for pattern in fallback_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            amount = match.group("amount")
            return ExtractionCandidate(
                value=amount,
                evidence=_line_evidence(text, match.start()),
                confidence=0.84,
                attributes=_mrp_attributes(text, match, amount, None),
            )
    return None


def _extract_month_year(text: str) -> ExtractionCandidate | None:
    numeric = re.search(
        r"(?:mfg|mfd|manufactured|packed|imported)\s*(?:date|on)?\s*[:\-]?\s*"
        r"(?P<month>0?[1-9]|1[0-2])[\/\-.](?P<year>(?:20)?\d{2})",
        text,
        flags=re.IGNORECASE,
    )
    if numeric:
        year = numeric.group("year")
        if len(year) == 2:
            year = f"20{year}"
        month = numeric.group("month").zfill(2)
        return ExtractionCandidate(
            value=f"{month}/{year}",
            evidence=_line_evidence(text, numeric.start()),
            confidence=0.94,
            attributes={"month": month, "year": year},
        )

    month_names = {
        "jan": "01",
        "feb": "02",
        "mar": "03",
        "apr": "04",
        "may": "05",
        "jun": "06",
        "jul": "07",
        "aug": "08",
        "sep": "09",
        "oct": "10",
        "nov": "11",
        "dec": "12",
    }
    named = re.search(
        r"(?:mfg|mfd|manufactured|packed|imported)[^\n]{0,20}"
        r"(?P<month>jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s*[,]?\s*(?P<year>20\d{2})",
        text,
        flags=re.IGNORECASE,
    )
    if named:
        month = month_names[named.group("month").lower()]
        year = named.group("year")
        return ExtractionCandidate(
            value=f"{month}/{year}",
            evidence=_line_evidence(text, named.start()),
            confidence=0.90,
            attributes={"month": month, "year": year},
        )
    return None


def _extract_best_before(text: str) -> ExtractionCandidate | None:
    match = re.search(
        r"(?:best\s+before|use\s+by|use\s+before|expiry|exp\.?\s*date)\s*[:\-]?\s*(?P<value>[^\n]{2,80})",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    value = match.group("value").strip()
    return ExtractionCandidate(
        value=value,
        evidence=_line_evidence(text, match.start()),
        confidence=0.92,
        attributes={"declaration": value},
    )


def _extract_dimensions(text: str) -> ExtractionCandidate | None:
    match = re.search(
        r"(?:dimensions?|size)\s*[:\-]?\s*"
        r"(?P<value>\d+(?:\.\d+)?\s*(?:cm|mm|m)?\s*[x×]\s*\d+(?:\.\d+)?"
        r"(?:\s*(?:cm|mm|m)?\s*[x×]\s*\d+(?:\.\d+)?)?\s*(?:cm|mm|m)?)",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    value = re.sub(r"\s+", " ", match.group("value")).strip()
    return ExtractionCandidate(
        value=value,
        evidence=_line_evidence(text, match.start()),
        confidence=0.90,
        attributes={"dimensions": value},
    )


def _extract_consumer_care(text: str) -> ExtractionCandidate | None:
    lines = text.splitlines()
    for line in lines:
        if not re.search(r"consumer\s*(?:care|complaint|helpline)", line, flags=re.IGNORECASE):
            continue
        email = re.search(r"[\w.+-]+@[\w.-]+\.[a-z]{2,}", line, flags=re.IGNORECASE)
        phone = re.search(r"(?:\+?91[\s-]?)?([6-9]\d{9})\b", line)
        if email or phone:
            attributes: dict[str, str] = {
                "address_detected": str(_looks_like_address(line)).lower(),
            }
            values: list[str] = []
            if email:
                attributes["email"] = email.group(0)
                values.append(email.group(0))
            if phone:
                attributes["phone"] = phone.group(1)
                values.append(phone.group(1))
            return ExtractionCandidate(
                value=" | ".join(values),
                evidence=_compact_evidence(line),
                confidence=0.94,
                attributes=attributes,
            )

    email = re.search(r"(?:care|support|consumer)[\w.+-]*@[\w.-]+\.[a-z]{2,}", text, flags=re.IGNORECASE)
    if email:
        return ExtractionCandidate(
            value=email.group(0),
            evidence=_compact_evidence(email.group(0)),
            confidence=0.82,
            attributes={"email": email.group(0), "address_detected": "false"},
        )
    return None


def _extract_unit_sale_price(text: str) -> ExtractionCandidate | None:
    match = re.search(
        r"(?:unit\s*(?:sale\s*)?price|usp)\s*[:\-]?\s*"
        r"(?P<currency>₹|rs\.?|inr)\s*(?P<amount>\d+(?:\.\d+)?)\s*(?:/|per)\s*"
        r"(?:(?P<quantity>\d+(?:\.\d+)?)\s*)?(?P<unit>g|kg|ml|l|piece|pc|number|unit)\b",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None

    currency = _currency_code(match.group("currency"))
    if not currency:
        return None
    amount = match.group("amount")
    quantity = match.group("quantity") or "1"
    unit = match.group("unit").lower()
    if unit in {"piece", "pc", "number", "unit"}:
        unit = "pc"
    return ExtractionCandidate(
        value=f"{currency} {amount} / {quantity} {unit}",
        evidence=_line_evidence(text, match.start()),
        confidence=0.93,
        attributes={
            "currency": currency,
            "amount": amount,
            "reference_quantity": quantity,
            "reference_unit": unit,
        },
    )


EXTRACTORS: tuple[tuple[str, str, Extractor], ...] = (
    ("manufacturer", "Manufacturer / Packer / Importer", _extract_manufacturer),
    ("country_origin", "Country of Origin / Manufacture / Assembly", _extract_country_origin),
    ("commodity_name", "Common / Generic Name", _extract_commodity_name),
    ("net_quantity", "Net Quantity", _extract_net_quantity),
    ("month_year", "Month & Year of Manufacture / Packing / Import", _extract_month_year),
    ("best_before", "Best Before / Use By", _extract_best_before),
    ("mrp", "Maximum Retail Price (MRP)", _extract_mrp),
    ("dimensions", "Size / Dimensions", _extract_dimensions),
    ("consumer_care", "Consumer Care Details", _extract_consumer_care),
    ("unit_sale_price", "Unit Sale Price", _extract_unit_sale_price),
)


def extract_declarations(
    raw_text: str,
    regions: Iterable[OcrRegion] = (),
) -> list[ExtractedDeclaration]:
    text = normalize_ocr_text(raw_text)
    region_list = list(regions)
    spatial_fields = extract_spatial_fields(region_list)
    declarations: list[ExtractedDeclaration] = []

    for key, label, extractor in EXTRACTORS:
        spatial_candidate = spatial_fields.get(key)
        if spatial_candidate is not None:
            candidate = ExtractionCandidate(
                value=spatial_candidate.value,
                evidence=spatial_candidate.evidence,
                confidence=spatial_candidate.confidence,
                attributes=spatial_candidate.attributes,
            )
            region_ids = list(spatial_candidate.region_ids)
        else:
            candidate = extractor(text)
            if not candidate:
                continue
            region_ids = matching_region_ids(candidate.evidence, region_list)

        declarations.append(
            ExtractedDeclaration(
                key=key,
                label=label,
                value=candidate.value,
                evidence=candidate.evidence,
                confidence=candidate.confidence,
                attributes=candidate.attributes,
                region_ids=region_ids,
            )
        )

    return declarations
