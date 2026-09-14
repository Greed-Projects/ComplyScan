from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterable

from ..models import ExtractedDeclaration, OcrRecoveryTrace, OcrVariantTrace
from ..vision.preprocessing import (
    CropCandidate,
    ImageVariant,
    InvalidImageError,
    attention_tile_variants,
    find_target_crops,
    image_from_bytes,
    preprocessing_variants,
)
from .base import OCRTextRegion, OcrEngine


@dataclass(frozen=True, slots=True)
class ReferenceHint:
    declaration_key: str
    locator: str
    evidence: str
    tax_inclusive_phrase: bool
    explicit_reference: bool = True


@dataclass(frozen=True, slots=True)
class RecoveryOutcome:
    declarations: tuple[ExtractedDeclaration, ...]
    regions: tuple[OCRTextRegion, ...]
    traces: tuple[OcrRecoveryTrace, ...]
    recovered_text: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _VariantObservation:
    crop: CropCandidate
    variant: ImageVariant
    text: str
    parsed: tuple[str, str, str] | None
    confidence: float
    regions: tuple[OCRTextRegion, ...]


_MRP_LABEL_RE = re.compile(
    r"(?:for\s+)?(?:mrp|m\.?r\.?p\.?|maximum\s+retail\s+price)",
    flags=re.IGNORECASE,
)

_LOCATOR_REFERENCE_RE = re.compile(
    r"(?P<evidence>(?:see|refer(?:\s+to)?)\s*(?:under|below|on|at|near)?\s*(?:the\s+)?"
    r"(?P<locator>seal|seam|crimp|bottom|base|cap|lid|neck|top))",
    flags=re.IGNORECASE,
)

_MRP_REFERENCE_RE = re.compile(
    r"(?P<evidence>(?:for\s+)?(?:mrp|m\.?r\.?p\.?|maximum\s+retail\s+price)"
    r"[\s\S]{0,180}?(?:see|refer(?:\s+to)?)\s*(?:under|below|on|at|near)?\s*(?:the\s+)?"
    r"(?P<locator>seal|seam|crimp|bottom|base|cap|lid|neck|top))",
    flags=re.IGNORECASE,
)

_TAX_INCLUSIVE_RE = re.compile(
    r"(?:inclusive\s+of\s+all\s+taxes|in[cdi1l]{1,4}\.?\s*of\s+all\s+taxes)",
    flags=re.IGNORECASE,
)

_CURRENCY_VALUE_RE = re.compile(
    r"(?P<currency>₹|r(?:s|5|e)\.?|inr)\s*[:.\-]?\s*"
    r"(?P<amount>[0-9Oo]{1,6}(?:\.[0-9Oo]{1,2})?)\s*(?:/\-)?",
    flags=re.IGNORECASE,
)

_UNIT_RATE_TAIL_RE = re.compile(
    r"^\s*(?:per|/)\s*(?:[0-9Oo]{0,4}\s*)?(?:g|kg|mg|ml|l|9)\b",
    flags=re.IGNORECASE,
)

# A common Indian package layout prints the MRP first and the unit sale price
# immediately afterwards, for example ``Rs.60 (Rs.0.21 per g)``. Faint
# dot-matrix OCR can drop the currency prefix from the first amount while still
# recognizing the currency on the parenthesized unit-rate value. In a targeted
# MRP recovery region, that structure is useful evidence for the leading amount
# without inventing a currency from thin air.
_LEADING_AMOUNT_BEFORE_UNIT_RATE_RE = re.compile(
    r"(?<![0-9Oo])(?P<amount>[0-9Oo]{1,6}(?:\.[0-9Oo]{1,2})?)\s*"
    r"\(\s*(?P<currency>₹|r(?:s|5|e)\.?|inr)\s*[:.\-]?\s*"
    r"[0-9Oo]{1,6}(?:\.[0-9Oo]{1,2})?\s*(?:per|/)\s*"
    r"(?:[0-9Oo]{0,4}\s*)?(?:g|kg|mg|ml|l|9)\b",
    flags=re.IGNORECASE,
)


_MAX_TARGET_CROPS = 2


def _compact(value: str, limit: int = 260) -> str:
    return re.sub(r"\s+", " ", value).strip()[:limit]


def _normalise_locator(raw_locator: str) -> str:
    return {
        "seam": "seal",
        "crimp": "seal",
        "base": "bottom",
        "cap": "top",
        "lid": "top",
        "neck": "top",
    }.get(raw_locator.lower(), raw_locator.lower())


def _nearby_tax_phrase(text: str, start: int, end: int, radius: int = 180) -> bool:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    return bool(_TAX_INCLUSIVE_RE.search(text[left:right]))


def detect_reference_hints(text: str) -> tuple[ReferenceHint, ...]:
    """Detect declaration locators even when OCR splits them into distant regions.

    Full-page OCR ordering is not guaranteed to keep a label and its locator
    adjacent. For example the real regression image produced ``orMRP(indl.of all
    taxes)-`` and, much later in the joined OCR stream, ``See under the seal.``.
    We therefore support both a compact direct pattern and semantic association
    between independently detected MRP-label and locator phrases.
    """

    hints: list[ReferenceHint] = []
    consumed_locator_spans: set[tuple[int, int]] = set()

    for match in _MRP_REFERENCE_RE.finditer(text):
        raw_locator = match.group("locator")
        evidence = _compact(match.group("evidence"))
        hints.append(
            ReferenceHint(
                declaration_key="mrp",
                locator=_normalise_locator(raw_locator),
                evidence=evidence,
                tax_inclusive_phrase=bool(_TAX_INCLUSIVE_RE.search(evidence)),
            )
        )
        locator_match = _LOCATOR_REFERENCE_RE.search(match.group("evidence"))
        if locator_match:
            consumed_locator_spans.add(
                (
                    match.start("evidence") + locator_match.start(),
                    match.start("evidence") + locator_match.end(),
                )
            )

    labels = list(_MRP_LABEL_RE.finditer(text))
    if labels:
        for locator_match in _LOCATOR_REFERENCE_RE.finditer(text):
            locator_span = (locator_match.start(), locator_match.end())
            if any(
                abs(locator_span[0] - start) <= 4 and abs(locator_span[1] - end) <= 4
                for start, end in consumed_locator_spans
            ):
                continue

            nearest_label = min(
                labels,
                key=lambda label: abs(label.start() - locator_match.start()),
            )
            # A package can have many OCR regions between the two phrases. The
            # association remains safe because both sides are semantically
            # specific: an MRP label and an explicit physical locator command.
            header_start = max(0, nearest_label.start() - 28)
            header_end = min(len(text), nearest_label.end() + 110)
            header = _compact(text[header_start:header_end], 150)
            locator_evidence = _compact(locator_match.group("evidence"), 90)
            evidence = _compact(f"{header} ... {locator_evidence}")
            hints.append(
                ReferenceHint(
                    declaration_key="mrp",
                    locator=_normalise_locator(locator_match.group("locator")),
                    evidence=evidence,
                    tax_inclusive_phrase=(
                        _nearby_tax_phrase(
                            text,
                            nearest_label.start(),
                            nearest_label.end(),
                        )
                        or bool(_TAX_INCLUSIVE_RE.search(evidence))
                    ),
                )
            )

    unique: list[ReferenceHint] = []
    seen: set[tuple[str, str]] = set()
    for hint in hints:
        key = (hint.declaration_key, hint.locator)
        if key in seen:
            continue
        seen.add(key)
        unique.append(hint)
    return tuple(unique)


def _text_key(value: str) -> str:
    return re.sub(r"[^a-z0-9₹]+", " ", value.lower()).strip()


def _reference_region_ids(
    evidence: str,
    regions: Iterable[OCRTextRegion],
) -> list[str]:
    evidence_tokens = set(_text_key(evidence).split())
    if not evidence_tokens:
        return []

    matches: list[str] = []
    evidence_key = _text_key(evidence)
    for region in regions:
        region_key = _text_key(region.text)
        if not region_key:
            continue
        region_tokens = set(region_key.split())
        overlap = len(evidence_tokens & region_tokens) / max(1, len(region_tokens))
        if region_key in evidence_key or overlap >= 0.50:
            matches.append(region.id)
    return matches


def _currency_code(token: str) -> str | None:
    normalized = token.strip().lower().replace(".", "")
    # ``Re`` is accepted only inside this targeted MRP recovery path. In the
    # supplied dot-matrix regression image PP-OCRv6 consistently reads the
    # trailing ``s`` of ``Rs`` as ``e``. It still carries explicit rupee
    # evidence and is not used as a global OCR substitution.
    if token == "₹" or normalized in {"rs", "r5", "re", "inr"}:
        return "INR"
    return None


def _canonical_amount(amount: str) -> str:
    clean = amount.replace("O", "0").replace("o", "0")
    try:
        value = Decimal(clean)
    except InvalidOperation:
        return clean
    if value == value.to_integral_value():
        return str(int(value))
    return format(value.normalize(), "f")


def _candidate_is_unit_rate(text: str, match: re.Match[str]) -> bool:
    # Unit sale price must not be mistaken for the referenced MRP. Restrict the
    # check to the short suffix immediately after the amount so unrelated later
    # text does not suppress a legitimate price. ``9`` is included because the
    # real OCR fixture repeatedly recognizes ``g`` as ``9``.
    suffix = text[match.end() : match.end() + 24]
    return bool(_UNIT_RATE_TAIL_RE.search(suffix))


def _parse_currency_value(text: str) -> tuple[str, str, str] | None:
    # Evaluate every explicit currency/amount candidate rather than returning
    # the first one. A localized MRP line can legally contain both the MRP and a
    # parenthesized unit sale price, e.g. ``Rs.60 (Rs.0.21 per g)``.
    explicit: list[tuple[str, str, str, bool, int]] = []
    for match in _CURRENCY_VALUE_RE.finditer(text):
        currency = _currency_code(match.group("currency"))
        if not currency:
            continue
        amount = _canonical_amount(match.group("amount"))
        explicit.append(
            (
                currency,
                amount,
                _compact(match.group(0)),
                _candidate_is_unit_rate(text, match),
                match.start(),
            )
        )

    # Prefer a non-unitized currency amount. Position is a deterministic
    # tiebreaker and matches normal package typography where MRP precedes unit
    # sale price on the same variable-print line.
    non_unit = [item for item in explicit if not item[3]]
    if non_unit:
        currency, amount, evidence, _, _ = min(non_unit, key=lambda item: item[4])
        return currency, amount, evidence

    # If OCR dropped the MRP's currency prefix but preserved a following
    # parenthesized rupee-denominated unit price, recover the leading amount
    # using that explicit nearby currency evidence. This remains scoped to the
    # referenced-MRP recovery pipeline; it is never used by generic extraction.
    structural = _LEADING_AMOUNT_BEFORE_UNIT_RATE_RE.search(text)
    if structural:
        currency = _currency_code(structural.group("currency"))
        if currency:
            amount = _canonical_amount(structural.group("amount"))
            return currency, amount, _compact(structural.group(0))

    # If every explicit value is a unit rate, do not return one as the MRP.
    return None


def _matching_regions(
    regions: Iterable[OCRTextRegion],
    currency: str,
    amount: str,
) -> list[OCRTextRegion]:
    amount_key = amount.rstrip("0").rstrip(".") if "." in amount else amount
    matches: list[OCRTextRegion] = []
    for region in regions:
        key = region.text.lower().replace(".", "")
        currency_hit = currency == "INR" and (
            "rs" in key or "r5" in key or "inr" in key or "₹" in region.text
        )
        amount_hit = amount in region.text or (amount_key and amount_key in region.text)
        if currency_hit or amount_hit:
            matches.append(region)
    return matches


def _observation_confidence(
    result_regions: Iterable[OCRTextRegion],
    parsed: tuple[str, str, str] | None,
) -> float:
    regions = list(result_regions)
    if not regions:
        return 0.0
    if parsed:
        currency, amount, _ = parsed
        relevant = _matching_regions(regions, currency, amount)
        if relevant:
            return max(region.confidence for region in relevant)
    return max(region.confidence for region in regions)


def _select_target_crops(crops: tuple[CropCandidate, ...]) -> tuple[CropCandidate, ...]:
    if len(crops) <= 1:
        return crops
    strongest, second = crops[0], crops[1]
    # If one visual candidate is clearly stronger, spend the expensive OCR
    # ensemble only there. Otherwise retain a second candidate for robustness.
    if strongest.score >= max(0.30, second.score * 1.30):
        return (strongest,)
    return crops[:_MAX_TARGET_CROPS]


def _observe_variants(
    *,
    crop: CropCandidate,
    variants: Iterable[ImageVariant],
    engine: OcrEngine,
) -> list[_VariantObservation]:
    observations: list[_VariantObservation] = []
    for variant in variants:
        result = engine.extract(variant.raw)
        text = result.text.strip()
        parsed = _parse_currency_value(text) if text else None
        observations.append(
            _VariantObservation(
                crop=crop,
                variant=variant,
                text=text,
                parsed=parsed,
                confidence=_observation_confidence(result.regions, parsed),
                regions=result.regions,
            )
        )
    return observations


def _direct_recognition_capability(engine: OcrEngine):
    recognizer = getattr(engine, "recognize_text_line", None)
    return recognizer if callable(recognizer) else None


def _direct_recognition_variants(
    raw_image: bytes,
    crop: CropCandidate,
) -> tuple[ImageVariant, ...]:
    """Return localized views suitable for detector-free text recognition.

    Full-region variants are intentionally excluded: the recognition model is
    designed to receive a text-line image, not a whole package region.
    """

    wide = tuple(
        variant
        for variant in preprocessing_variants(raw_image, crop)
        if variant.name in {
            "line-original",
            "line-clahe",
            "line-clahe-inverted",
            "line-gamma-inverted",
        }
    )
    return (*wide, *attention_tile_variants(raw_image, crop))


def _collect_direct_recognition_observations(
    raw_image: bytes,
    engine: OcrEngine,
    crops: tuple[CropCandidate, ...],
) -> tuple[_VariantObservation, ...]:
    recognizer = _direct_recognition_capability(engine)
    if recognizer is None:
        return tuple()

    observations: list[_VariantObservation] = []
    for crop in crops:
        for source_variant in _direct_recognition_variants(raw_image, crop):
            result = recognizer(source_variant.raw)
            text = result.text.strip()
            parsed = _parse_currency_value(text) if text else None
            direct_variant = ImageVariant(
                name=f"direct-{source_variant.name}",
                family=f"direct-{source_variant.family}",
                raw=source_variant.raw,
                source_x=source_variant.source_x,
                source_y=source_variant.source_y,
                source_width=source_variant.source_width,
                source_height=source_variant.source_height,
            )
            observations.append(
                _VariantObservation(
                    crop=crop,
                    variant=direct_variant,
                    text=text,
                    parsed=parsed,
                    confidence=_observation_confidence(result.regions, parsed),
                    regions=result.regions,
                )
            )
    return tuple(observations)


def _selected_target_crops(
    raw_image: bytes,
    locator: str,
) -> tuple[CropCandidate, ...]:
    return _select_target_crops(find_target_crops(raw_image, locator))


def _collect_variant_observations(
    raw_image: bytes,
    locator: str,
    engine: OcrEngine,
    crops: tuple[CropCandidate, ...] | None = None,
) -> tuple[_VariantObservation, ...]:
    observations: list[_VariantObservation] = []
    selected = crops or _selected_target_crops(raw_image, locator)
    for crop in selected:
        observations.extend(
            _observe_variants(
                crop=crop,
                variants=preprocessing_variants(raw_image, crop),
                engine=engine,
            )
        )
    return tuple(observations)


def _collect_attention_observations(
    raw_image: bytes,
    engine: OcrEngine,
    crops: tuple[CropCandidate, ...],
) -> tuple[_VariantObservation, ...]:
    """Second-stage spatial attention for a wide seal/text band.

    The first ensemble deliberately keeps runtime bounded. If it cannot form a
    candidate, this stage zooms into overlapping horizontal windows so faint
    characters are not sacrificed by extreme line aspect ratios.
    """

    observations: list[_VariantObservation] = []
    for crop in crops:
        observations.extend(
            _observe_variants(
                crop=crop,
                variants=attention_tile_variants(raw_image, crop),
                engine=engine,
            )
        )
    return tuple(observations)


def _candidate_rank(
    observations: list[_VariantObservation],
) -> tuple[int, int, float]:
    families = {item.variant.family for item in observations}
    mean_confidence = (
        sum(item.confidence for item in observations) / len(observations)
        if observations
        else 0.0
    )
    return len(families), len(observations), mean_confidence


def _winning_candidate(
    observations: Iterable[_VariantObservation],
) -> tuple[
    tuple[str, str] | None,
    list[_VariantObservation],
    bool,
]:
    groups: dict[tuple[str, str], list[_VariantObservation]] = {}
    for observation in observations:
        if not observation.parsed:
            continue
        currency, amount, _ = observation.parsed
        groups.setdefault((currency, amount), []).append(observation)

    if not groups:
        return None, [], False

    ordered = sorted(
        groups.items(),
        key=lambda item: _candidate_rank(item[1]),
        reverse=True,
    )
    winner_key, winner = ordered[0]
    winner_rank = _candidate_rank(winner)
    runner_rank = _candidate_rank(ordered[1][1]) if len(ordered) > 1 else None

    families, votes, mean_confidence = winner_rank
    clear_of_runner = runner_rank is None or winner_rank > runner_rank
    consensus = clear_of_runner and (
        families >= 2
        or votes >= 3
        or (votes >= 2 and mean_confidence >= 0.86)
        or (votes == 1 and mean_confidence >= 0.96)
    )
    return winner_key, winner, consensus


def _map_region(
    region: OCRTextRegion,
    variant: ImageVariant,
    image_width: int,
    image_height: int,
    region_id: str,
    source: str,
) -> OCRTextRegion:
    mapped: list[tuple[float, float]] = []
    for x, y in region.polygon:
        mapped.append(
            (
                min(
                    1.0,
                    max(
                        0.0,
                        (variant.source_x + x * variant.source_width)
                        / max(image_width, 1),
                    ),
                ),
                min(
                    1.0,
                    max(
                        0.0,
                        (variant.source_y + y * variant.source_height)
                        / max(image_height, 1),
                    ),
                ),
            )
        )
    return OCRTextRegion(
        id=region_id,
        text=region.text,
        confidence=region.confidence,
        polygon=tuple(mapped),
        source=source,
    )


def _variant_traces(
    observations: Iterable[_VariantObservation],
) -> list[OcrVariantTrace]:
    traces: list[OcrVariantTrace] = []
    for observation in observations:
        parsed_value = None
        if observation.parsed:
            currency, amount, _ = observation.parsed
            parsed_value = f"{currency} {amount}"
        traces.append(
            OcrVariantTrace(
                crop=observation.crop.label,
                variant=observation.variant.name,
                family=observation.variant.family,
                text=_compact(observation.text, 320) if observation.text else None,
                parsed_value=parsed_value,
                confidence=observation.confidence,
            )
        )
    return traces


def _best_diagnostic_text(observations: Iterable[_VariantObservation]) -> str | None:
    nonempty = [item for item in observations if item.text]
    if not nonempty:
        return None
    best = max(
        nonempty,
        key=lambda item: (
            item.parsed is not None,
            item.confidence,
            len(item.text),
        ),
    )
    return _compact(best.text, 500)


def recover_referenced_declarations(
    raw_image: bytes,
    primary_text: str,
    existing_declarations: Iterable[ExtractedDeclaration],
    engine: OcrEngine,
    primary_regions: Iterable[OCRTextRegion] = (),
) -> RecoveryOutcome:
    existing_by_key = {item.key: item for item in existing_declarations}
    hints = list(detect_reference_hints(primary_text))
    primary_region_list = list(primary_regions)

    existing_mrp = existing_by_key.get("mrp")
    complete_direct_mrp = bool(
        existing_mrp
        and existing_mrp.attributes.get("currency") == "INR"
        and existing_mrp.attributes.get("amount")
    )

    # Do not make difficult-region recovery depend entirely on the *first* OCR
    # pass successfully reading a locator such as "See under the seal". The
    # hand-held Maggi regression photo demonstrates the exact failure mode: the
    # MRP line is physically present and visually recoverable, but primary OCR
    # can miss enough of the printed locator that no ReferenceHint is formed.
    #
    # When MRP is still unresolved, a strong visual seal/crimp candidate is a
    # sufficient trigger for a bounded, detector-free search. This fallback is
    # evidence discovery only; if it fails we do *not* manufacture an
    # ``mrp_reference`` fact or downgrade a true missing declaration to Review.
    if not hints and not complete_direct_mrp:
        try:
            seal_candidates = _selected_target_crops(raw_image, "seal")
        except InvalidImageError:
            # Text-only/fake OCR engines used by API tests do not necessarily
            # carry decodable image bytes. Primary OCR extraction remains
            # usable; only the optional visual fallback is skipped.
            seal_candidates = tuple()
        strongest_seal = seal_candidates[0] if seal_candidates else None
        semantic_mrp_clue = bool(
            _MRP_LABEL_RE.search(primary_text) or _TAX_INCLUSIVE_RE.search(primary_text)
        )
        visual_seal_clue = bool(
            strongest_seal
            and strongest_seal.label != "seal-middle-fallback"
            and strongest_seal.score >= 0.70
        )
        if semantic_mrp_clue or visual_seal_clue:
            hints.append(
                ReferenceHint(
                    declaration_key="mrp",
                    locator="seal",
                    evidence=(
                        "Primary OCR did not resolve MRP or a reliable locator; "
                        "PackCheck searched the visually detected seal/crimp "
                        "variable-print region."
                    ),
                    tax_inclusive_phrase=bool(_TAX_INCLUSIVE_RE.search(primary_text)),
                    explicit_reference=False,
                )
            )

    if not hints:
        return RecoveryOutcome(tuple(), tuple(), tuple(), tuple())

    image = image_from_bytes(raw_image)
    image_height, image_width = image.shape[:2]
    recovered_declarations: list[ExtractedDeclaration] = []
    recovered_regions: list[OCRTextRegion] = []
    traces: list[OcrRecoveryTrace] = []
    recovered_text: list[str] = []
    targeted_id = 1

    for hint in hints:
        hint_region_ids = _reference_region_ids(hint.evidence, primary_region_list)
        existing = existing_by_key.get(hint.declaration_key)
        if (
            existing
            and existing.attributes.get("currency") == "INR"
            and existing.attributes.get("amount")
        ):
            if (
                hint.tax_inclusive_phrase
                and existing.attributes.get("tax_inclusive_phrase") != "true"
            ):
                enriched_attributes = dict(existing.attributes)
                enriched_attributes.update(
                    {
                        "tax_inclusive_phrase": "true",
                        "source": "direct_plus_reference",
                        "locator": hint.locator,
                        "reference_evidence": hint.evidence,
                    }
                )
                recovered_declarations.append(
                    ExtractedDeclaration(
                        key=existing.key,
                        label=existing.label,
                        value=existing.value,
                        evidence=_compact(f"{existing.evidence} -> {hint.evidence}"),
                        confidence=min(0.96, max(existing.confidence, 0.90)),
                        attributes=enriched_attributes,
                        region_ids=list(
                            dict.fromkeys([*existing.region_ids, *hint_region_ids])
                        ),
                    )
                )
                message = (
                    "Direct MRP value was already extracted; the locator reference "
                    "supplied the tax-inclusive wording, so targeted OCR was unnecessary."
                )
            else:
                message = (
                    "Direct declaration value was already extracted; targeted OCR was "
                    "unnecessary."
                )

            traces.append(
                OcrRecoveryTrace(
                    declaration_key=hint.declaration_key,
                    locator=hint.locator,
                    reference_evidence=hint.evidence,
                    attempted=False,
                    resolved=True,
                    region_ids=list(
                        dict.fromkeys([*existing.region_ids, *hint_region_ids])
                    ),
                    message=message,
                )
            )
            continue

        selected_crops = _selected_target_crops(raw_image, hint.locator)
        observations: list[_VariantObservation] = []
        direct_recognition_attempted = False

        # For proactive visual fallback we already have a localized variable-
        # print band. Go straight to detector-free text recognition first;
        # this is both faster and more reliable for faint dot-matrix seals than
        # asking the text detector to rediscover a line we have already found.
        if not hint.explicit_reference:
            direct_observations = _collect_direct_recognition_observations(
                raw_image,
                engine,
                selected_crops,
            )
            if direct_observations:
                direct_recognition_attempted = True
                observations.extend(direct_observations)

        if not observations:
            observations.extend(
                _collect_variant_observations(
                    raw_image,
                    hint.locator,
                    engine,
                    crops=selected_crops,
                )
            )

        winner_key, winner_observations, consensus = _winning_candidate(observations)

        # The real Maggi regression image proved that the correct seal can be
        # localized while a very wide OCR view still reads only the easier
        # JUL/26 / batch portion and misses the faint MRP at the left. Mimic
        # human visual attention by zooming into overlapping windows only after
        # the inexpensive wide ensemble fails.
        if not consensus and hint.explicit_reference:
            observations.extend(
                _collect_attention_observations(
                    raw_image,
                    engine,
                    selected_crops,
                )
            )
            winner_key, winner_observations, consensus = _winning_candidate(observations)

        # If the end-to-end OCR pipeline still cannot read an already-localized
        # text line, bypass text detection completely and invoke the PP-OCRv6
        # recognition module on the line/attention views. This is the decisive
        # experiment for faint dot-matrix printing such as the Maggi seal.
        if not consensus and hint.explicit_reference:
            direct_observations = _collect_direct_recognition_observations(
                raw_image,
                engine,
                selected_crops,
            )
            if direct_observations:
                direct_recognition_attempted = True
                observations.extend(direct_observations)
                winner_key, winner_observations, consensus = _winning_candidate(
                    observations
                )

        # A proactive direct-recognition probe can still fail. Fall back to the
        # normal detection ensemble before giving up so unusual but valid print
        # styles are not penalized by the optimization above.
        if not consensus and not hint.explicit_reference:
            observations.extend(
                _collect_variant_observations(
                    raw_image,
                    hint.locator,
                    engine,
                    crops=selected_crops,
                )
            )
            winner_key, winner_observations, consensus = _winning_candidate(observations)
            if not consensus:
                observations.extend(
                    _collect_attention_observations(
                        raw_image,
                        engine,
                        selected_crops,
                    )
                )
                winner_key, winner_observations, consensus = _winning_candidate(
                    observations
                )

        region_ids: list[str] = []
        strategy: str | None = None
        resolved = False

        if winner_key and consensus:
            currency, amount = winner_key
            mapped_value_regions: list[OCRTextRegion] = []
            for observation in winner_observations:
                source = (
                    f"ensemble:{hint.locator}:{observation.crop.label}:"
                    f"{observation.variant.name}"
                )
                matching = _matching_regions(
                    observation.regions,
                    currency,
                    amount,
                )
                if not matching:
                    matching = list(observation.regions)
                for region in matching:
                    mapped = _map_region(
                        region,
                        observation.variant,
                        image_width,
                        image_height,
                        f"t{targeted_id}",
                        source,
                    )
                    targeted_id += 1
                    mapped_value_regions.append(mapped)

            recovered_regions.extend(mapped_value_regions)
            region_ids = [
                *hint_region_ids,
                *(region.id for region in mapped_value_regions),
            ]
            families = {item.variant.family for item in winner_observations}
            votes = len(winner_observations)
            mean_confidence = sum(
                item.confidence for item in winner_observations
            ) / max(votes, 1)
            winner_used_direct_recognition = any(
                item.variant.name.startswith("direct-")
                for item in winner_observations
            )
            strategy = (
                "direct-text-recognition-ensemble"
                if winner_used_direct_recognition
                else "image-variant-ensemble"
            )
            value_evidence = next(
                (
                    item.parsed[2]
                    for item in winner_observations
                    if item.parsed is not None
                ),
                f"{currency} {amount}",
            )
            recovered_declarations.append(
                ExtractedDeclaration(
                    key="mrp",
                    label="Maximum Retail Price (MRP)",
                    value=f"{currency} {amount}",
                    evidence=_compact(f"{hint.evidence} -> {value_evidence}"),
                    confidence=min(
                        0.96,
                        max(0.68, 0.58 + 0.05 * len(families) + 0.20 * mean_confidence),
                    ),
                    attributes={
                        "currency": currency,
                        "amount": amount,
                        "tax_inclusive_phrase": str(hint.tax_inclusive_phrase).lower(),
                        "source": (
                            "referenced_region_ensemble"
                            if hint.explicit_reference
                            else "required_mrp_visual_fallback"
                        ),
                        "locator": hint.locator,
                        "recovery_strategy": strategy,
                        "reference_evidence": hint.evidence,
                        "ensemble_votes": str(votes),
                        "ensemble_families": str(len(families)),
                    },
                    region_ids=region_ids,
                )
            )
            winner_texts = [
                item.text for item in winner_observations if item.text
            ]
            if winner_texts:
                recovered_text.append(
                    f"[Image-variant OCR ensemble: MRP via {hint.locator}]\n"
                    + "\n---\n".join(winner_texts[:4])
                )
            resolved = True
            existing_by_key["mrp"] = recovered_declarations[-1]

        if not resolved and hint.explicit_reference:
            recovered_declarations.append(
                ExtractedDeclaration(
                    key="mrp_reference",
                    label="MRP locator reference",
                    value=f"See {hint.locator}",
                    evidence=hint.evidence,
                    confidence=0.82,
                    attributes={
                        "locator": hint.locator,
                        "tax_inclusive_phrase": str(hint.tax_inclusive_phrase).lower(),
                        "source": "unresolved_reference",
                    },
                    region_ids=hint_region_ids,
                )
            )

        if resolved and winner_key:
            families = len({item.variant.family for item in winner_observations})
            if hint.explicit_reference:
                message = (
                    f"Referenced declaration recovered by image-variant OCR consensus: "
                    f"{len(winner_observations)} agreeing variants across {families} "
                    f"preprocessing families."
                )
            else:
                message = (
                    "Primary OCR did not resolve MRP, so PackCheck searched the "
                    "visually detected seal/crimp region and recovered the declaration "
                    f"by OCR consensus: {len(winner_observations)} agreeing variants "
                    f"across {families} preprocessing families."
                )
        elif winner_key:
            candidate_currency, candidate_amount = winner_key
            message = (
                f"The image-variant OCR ensemble found candidate "
                f"{candidate_currency} {candidate_amount}, but independent evidence did "
                "not meet the conservative consensus threshold; manual review is required."
            )
        else:
            if direct_recognition_attempted:
                if hint.explicit_reference:
                    message = (
                        "A declaration reference was detected, but neither the end-to-end "
                        "OCR variants nor detector-free direct text recognition produced a "
                        "reliable currency/amount candidate."
                    )
                else:
                    message = (
                        "Primary OCR did not resolve MRP. PackCheck searched the visually "
                        "detected seal/crimp region, but localized OCR did not produce a "
                        "reliable currency/amount candidate."
                    )
            else:
                message = (
                    "A declaration reference was detected, but none of the localized image "
                    "variants produced a reliable currency/amount candidate."
                )

        traces.append(
            OcrRecoveryTrace(
                declaration_key=hint.declaration_key,
                locator=hint.locator,
                reference_evidence=hint.evidence,
                attempted=True,
                resolved=resolved,
                attempts=len(observations),
                strategy=(
                    strategy
                    or (
                        "image-variant-ensemble+direct-text-recognition"
                        if direct_recognition_attempted
                        else "image-variant-ensemble"
                    )
                ),
                recovered_text=_best_diagnostic_text(observations),
                region_ids=region_ids,
                variants=_variant_traces(observations),
                message=message,
            )
        )

    return RecoveryOutcome(
        declarations=tuple(recovered_declarations),
        regions=tuple(recovered_regions),
        traces=tuple(traces),
        recovered_text=tuple(recovered_text),
    )
