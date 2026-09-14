from __future__ import annotations

from pathlib import Path

from app.analyzer import analyze_text_with_declarations
from app.ocr.base import OCRResult, OCRTextRegion
from app.ocr.targeted_recovery import (
    _parse_currency_value,
    detect_reference_hints,
    find_target_crops,
    recover_referenced_declarations,
)


FIXTURE = Path(__file__).parent / "fixtures" / "maggi-mrp-under-seal.jpeg"
HANDHELD_FIXTURE = (
    Path(__file__).parent / "fixtures" / "maggi-mrp-under-seal-handheld.jpeg"
)
REFERENCE_TEXT = """
FOR MRP (incl. of all taxes):
(Lot No.-MFD)- USE BY:
See under the seal.
"""


class FakeTargetedEngine:
    def __init__(self, result_text: str = "Rs 60/-") -> None:
        self.calls = 0
        self.result_text = result_text

    @property
    def name(self) -> str:
        return "fake-targeted-engine"

    def extract(self, raw: bytes) -> OCRResult:
        self.calls += 1
        if not self.result_text:
            return OCRResult(text="", engine=self.name, width=1000, height=200)
        return OCRResult(
            text=self.result_text,
            engine=self.name,
            width=1000,
            height=200,
            regions=(
                OCRTextRegion(
                    id="r1",
                    text=self.result_text,
                    confidence=0.91,
                    polygon=((0.15, 0.35), (0.36, 0.35), (0.36, 0.62), (0.15, 0.62)),
                ),
            ),
        )


def _declaration_map(items):
    return {item.key: item for item in items}


def test_reference_hint_supports_multiline_see_under_seal_wording():
    hints = detect_reference_hints(REFERENCE_TEXT)

    assert len(hints) == 1
    assert hints[0].declaration_key == "mrp"
    assert hints[0].locator == "seal"
    assert hints[0].tax_inclusive_phrase is True
    assert "See under the seal" in hints[0].evidence


def test_fixture_seal_detector_finds_long_dark_horizontal_band():
    candidates = find_target_crops(FIXTURE.read_bytes(), "seal")

    assert candidates
    strongest = candidates[0]
    # The actual black crimp/seal in the supplied regression image spans most
    # of the width and sits in the upper-middle portion of the photograph.
    assert strongest.width >= 0.80 * 1600
    assert strongest.y < 0.50 * 902
    assert strongest.y + strongest.height > 0.30 * 902


def test_handheld_fixture_seal_detector_uses_projection_instead_of_middle_fallback():
    candidates = find_target_crops(HANDHELD_FIXTURE.read_bytes(), "seal")

    assert candidates
    strongest = candidates[0]
    assert strongest.label.startswith("seal-row-")
    assert strongest.score >= 0.35
    assert strongest.width >= 0.70 * 1600
    assert 0.30 * 902 <= strongest.y <= 0.50 * 902
    assert strongest.height <= 0.18 * 902


def test_referenced_mrp_recovery_returns_structured_inr_fact_and_mapped_region():
    engine = FakeTargetedEngine("Rs 60/-")
    outcome = recover_referenced_declarations(
        FIXTURE.read_bytes(),
        REFERENCE_TEXT,
        existing_declarations=[],
        engine=engine,
    )

    declarations = _declaration_map(outcome.declarations)
    assert declarations["mrp"].value == "INR 60"
    assert declarations["mrp"].attributes["amount"] == "60"
    assert declarations["mrp"].attributes["currency"] == "INR"
    assert declarations["mrp"].attributes["tax_inclusive_phrase"] == "true"
    assert declarations["mrp"].attributes["source"] == "referenced_region_ensemble"
    assert declarations["mrp"].attributes["locator"] == "seal"
    assert outcome.traces[0].resolved is True
    assert engine.calls >= 2
    assert outcome.regions
    assert outcome.regions[0].id.startswith("t")
    assert outcome.regions[0].source.startswith("ensemble:seal:")
    assert all(0.0 <= coordinate <= 1.0 for point in outcome.regions[0].polygon for coordinate in point)


def test_targeted_parser_tolerates_common_dot_matrix_ocr_confusions():
    engine = FakeTargetedEngine("R5 6O/-")
    outcome = recover_referenced_declarations(
        FIXTURE.read_bytes(),
        REFERENCE_TEXT,
        existing_declarations=[],
        engine=engine,
    )

    mrp = _declaration_map(outcome.declarations)["mrp"]
    assert mrp.value == "INR 60"
    assert mrp.attributes["amount"] == "60"


def test_direct_mrp_skips_targeted_ocr():
    from app.extraction import extract_declarations

    direct_text = REFERENCE_TEXT + "\nMRP: Rs 60 inclusive of all taxes"
    direct = extract_declarations(direct_text)
    engine = FakeTargetedEngine()

    outcome = recover_referenced_declarations(
        FIXTURE.read_bytes(),
        direct_text,
        existing_declarations=direct,
        engine=engine,
    )

    assert engine.calls == 0
    assert outcome.declarations == ()
    assert outcome.traces[0].attempted is False
    assert outcome.traces[0].resolved is True


def test_unresolved_reference_is_review_not_false_missing_mrp_failure():
    engine = FakeTargetedEngine("")
    outcome = recover_referenced_declarations(
        FIXTURE.read_bytes(),
        REFERENCE_TEXT,
        existing_declarations=[],
        engine=engine,
    )
    declarations, checks, _ = analyze_text_with_declarations(
        REFERENCE_TEXT + "\nProduct Name: Noodles\nNet Quantity: 280 g\nManufactured by: Example Foods, Delhi 110001",
        supplemental_declarations=outcome.declarations,
    )
    keyed_checks = {check.key: check for check in checks}
    keyed_declarations = _declaration_map(declarations)

    assert "mrp_reference" in keyed_declarations
    assert keyed_checks["mrp"].status == "warning"
    assert "multi-view OCR recovery path could not establish" in keyed_checks["mrp"].message


def test_reference_can_supply_tax_wording_to_direct_mrp_without_extra_ocr():
    from app.extraction import extract_declarations

    direct_text = REFERENCE_TEXT + "\nMRP: Rs 60"
    direct = extract_declarations(direct_text)
    assert _declaration_map(direct)["mrp"].attributes["tax_inclusive_phrase"] == "false"

    engine = FakeTargetedEngine()
    outcome = recover_referenced_declarations(
        FIXTURE.read_bytes(),
        direct_text,
        existing_declarations=direct,
        engine=engine,
    )

    assert engine.calls == 0
    mrp = _declaration_map(outcome.declarations)["mrp"]
    assert mrp.value == "INR 60"
    assert mrp.attributes["tax_inclusive_phrase"] == "true"
    assert mrp.attributes["source"] == "direct_plus_reference"


def test_incomplete_direct_mrp_without_currency_still_runs_targeted_recovery():
    from app.extraction import extract_declarations

    direct_text = REFERENCE_TEXT + "\nMRP: 60"
    direct = extract_declarations(direct_text)
    assert "currency" not in _declaration_map(direct)["mrp"].attributes

    engine = FakeTargetedEngine("Rs 60/-")
    outcome = recover_referenced_declarations(
        FIXTURE.read_bytes(),
        direct_text,
        existing_declarations=direct,
        engine=engine,
    )

    assert engine.calls >= 2
    assert _declaration_map(outcome.declarations)["mrp"].attributes["currency"] == "INR"


def test_reference_hint_associates_split_full_page_ocr_regions():
    noisy_primary_text = """
Maidal, Palm oil, iodized salt
orMRP(indl.of all taxes)-
Plot no. SM-38, Sanand II, GIDC Industrial Estate
FOR SALE IN INDIA, NEPAL AND BHUTAN ONLY
Lot No.-MFD.-USE BY:
STORAGE ADVICE
See under the seal.
"""

    hints = detect_reference_hints(noisy_primary_text)

    assert len(hints) == 1
    assert hints[0].locator == "seal"
    assert hints[0].tax_inclusive_phrase is True
    assert "See under the seal" in hints[0].evidence


def test_variant_plan_contains_line_localization_inversion_and_morphology():
    from app.ocr.targeted_recovery import preprocessing_variants

    crop = find_target_crops(FIXTURE.read_bytes(), "seal")[0]
    variants = preprocessing_variants(FIXTURE.read_bytes(), crop)
    names = {item.name for item in variants}
    families = {item.family for item in variants}

    assert "line-original" in names
    assert "line-clahe-inverted" in names
    assert "line-tophat" in names
    assert "line-adaptive" in names
    assert "polarity" in families
    assert "morphology" in families

    line_variant = next(item for item in variants if item.name == "line-original")
    assert line_variant.source_height < crop.height
    assert line_variant.source_width <= crop.width


def test_variant_ensemble_trace_preserves_each_attempt_for_diagnostics():
    engine = FakeTargetedEngine("Rs 60/-")
    outcome = recover_referenced_declarations(
        FIXTURE.read_bytes(),
        REFERENCE_TEXT,
        existing_declarations=[],
        engine=engine,
    )

    trace = outcome.traces[0]
    assert trace.strategy == "image-variant-ensemble"
    assert trace.attempts == engine.calls
    assert len(trace.variants) == trace.attempts
    assert {item.parsed_value for item in trace.variants} == {"INR 60"}
    assert len({item.family for item in trace.variants}) >= 4

class SequenceTargetedEngine:
    def __init__(self, texts: list[str], confidence: float = 0.90) -> None:
        self.texts = texts
        self.confidence = confidence
        self.calls = 0

    @property
    def name(self) -> str:
        return "sequence-targeted-engine"

    def extract(self, raw: bytes) -> OCRResult:
        index = self.calls
        self.calls += 1
        text = self.texts[index] if index < len(self.texts) else ""
        if not text:
            return OCRResult(text="", engine=self.name, width=1000, height=200)
        return OCRResult(
            text=text,
            engine=self.name,
            width=1000,
            height=200,
            regions=(
                OCRTextRegion(
                    id="r1",
                    text=text,
                    confidence=self.confidence,
                    polygon=((0.15, 0.35), (0.36, 0.35), (0.36, 0.62), (0.15, 0.62)),
                ),
            ),
        )


def test_single_moderate_confidence_variant_is_reported_but_not_auto_resolved():
    engine = SequenceTargetedEngine(["Rs 60/-"], confidence=0.90)
    outcome = recover_referenced_declarations(
        FIXTURE.read_bytes(),
        REFERENCE_TEXT,
        existing_declarations=[],
        engine=engine,
    )

    declarations = _declaration_map(outcome.declarations)
    trace = outcome.traces[0]
    assert "mrp" not in declarations
    assert "mrp_reference" in declarations
    assert trace.resolved is False
    assert any(item.parsed_value == "INR 60" for item in trace.variants)
    assert "consensus threshold" in trace.message


def test_two_preprocessing_families_can_form_consensus():
    # Variant order starts full-original (baseline), full-clahe (local-contrast).
    engine = SequenceTargetedEngine(["Rs 60/-", "R5 6O/-"], confidence=0.90)
    outcome = recover_referenced_declarations(
        FIXTURE.read_bytes(),
        REFERENCE_TEXT,
        existing_declarations=[],
        engine=engine,
    )

    mrp = _declaration_map(outcome.declarations)["mrp"]
    assert mrp.value == "INR 60"
    assert mrp.attributes["ensemble_votes"] == "2"
    assert mrp.attributes["ensemble_families"] == "2"

def test_attention_tiles_cover_wide_seal_with_overlapping_narrow_views():
    from app.vision.preprocessing import attention_tile_variants

    crop = find_target_crops(FIXTURE.read_bytes(), "seal")[0]
    variants = attention_tile_variants(FIXTURE.read_bytes(), crop)

    assert variants
    assert len(variants) >= 6
    assert len(variants) <= 10
    assert {item.family for item in variants} == {
        "attention-local-contrast",
        "attention-polarity",
    }

    clahe_tiles = [item for item in variants if item.name.endswith("-clahe")]
    assert len(clahe_tiles) >= 3
    assert clahe_tiles[0].source_x <= crop.x + int(crop.width * 0.08)
    assert clahe_tiles[-1].source_x + clahe_tiles[-1].source_width >= (
        crop.x + int(crop.width * 0.90)
    )
    assert all(item.source_width < crop.width * 0.60 for item in clahe_tiles)


def test_attention_stage_runs_only_after_wide_ensemble_fails_and_can_resolve():
    # The normal plan contains ten variants. Make all of them fail, then let
    # the first two attention variants independently recognize the same MRP.
    engine = SequenceTargetedEngine(
        [""] * 10 + ["Rs 60/-", "R5 6O/-"],
        confidence=0.92,
    )
    outcome = recover_referenced_declarations(
        FIXTURE.read_bytes(),
        REFERENCE_TEXT,
        existing_declarations=[],
        engine=engine,
    )

    mrp = _declaration_map(outcome.declarations)["mrp"]
    trace = outcome.traces[0]
    assert mrp.value == "INR 60"
    assert trace.resolved is True
    assert trace.attempts > 10
    assert any(item.variant.startswith("attention-") for item in trace.variants)
    agreeing_attention = [
        item
        for item in trace.variants
        if item.variant.startswith("attention-") and item.parsed_value == "INR 60"
    ]
    assert len(agreeing_attention) == 2



class DirectRecognitionTargetedEngine:
    def __init__(self) -> None:
        self.calls = 0
        self.direct_calls = 0

    @property
    def name(self) -> str:
        return "direct-recognition-targeted-engine"

    def extract(self, raw: bytes) -> OCRResult:
        self.calls += 1
        return OCRResult(text="", engine=self.name, width=1000, height=200)

    def recognize_text_line(self, raw: bytes) -> OCRResult:
        # Direct-variant order begins with four wide line views, then the two
        # attention-01 views, then attention-02 CLAHE / inverted. Model the real
        # Maggi observation: only attention window 02 contains a clean full MRP.
        index = self.direct_calls
        self.direct_calls += 1
        text = ""
        if index == 6:
            text = "Rs 60/- B.21"
        elif index == 7:
            text = "R5 6O/- B.21"

        if not text:
            return OCRResult(
                text="",
                engine=self.name,
                width=1000,
                height=220,
            )
        return OCRResult(
            text=text,
            engine=self.name,
            width=1000,
            height=220,
            regions=(
                OCRTextRegion(
                    id="dr1",
                    text=text,
                    confidence=0.93,
                    polygon=((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)),
                    source="direct-recognition",
                ),
            ),
        )


def test_detector_free_recognition_runs_after_detection_ensembles_fail():
    engine = DirectRecognitionTargetedEngine()
    outcome = recover_referenced_declarations(
        FIXTURE.read_bytes(),
        REFERENCE_TEXT,
        existing_declarations=[],
        engine=engine,
    )

    declarations = _declaration_map(outcome.declarations)
    trace = outcome.traces[0]

    assert declarations["mrp"].value == "INR 60"
    assert declarations["mrp"].attributes["recovery_strategy"] == (
        "direct-text-recognition-ensemble"
    )
    assert engine.calls >= 20
    assert engine.direct_calls >= 8
    assert trace.resolved is True
    assert trace.strategy == "direct-text-recognition-ensemble"
    direct_hits = [
        item
        for item in trace.variants
        if item.variant.startswith("direct-") and item.parsed_value == "INR 60"
    ]
    assert len(direct_hits) == 2
    assert len({item.family for item in direct_hits}) == 2


def test_missing_reference_hint_can_recover_mrp_from_strong_visual_seal():
    # Model the real frontend failure: primary OCR misses enough of the
    # "For MRP ... See under seal" wording that no ReferenceHint exists, while
    # detector-free recognition can still read the variable-print line.
    engine = DirectRecognitionTargetedEngine()
    primary_text = """
    NESTLE CONSUMER CARE
    Mfg. By: Nestle India Limited
    Lot No.-MFD.-USE BY:
    NET QUANTITY:
    """

    outcome = recover_referenced_declarations(
        HANDHELD_FIXTURE.read_bytes(),
        primary_text,
        existing_declarations=[],
        engine=engine,
    )

    declarations = _declaration_map(outcome.declarations)
    assert declarations["mrp"].value == "INR 60"
    assert declarations["mrp"].attributes["source"] == (
        "required_mrp_visual_fallback"
    )
    assert "mrp_reference" not in declarations
    assert outcome.traces[0].resolved is True
    assert outcome.traces[0].locator == "seal"
    assert outcome.traces[0].strategy == "direct-text-recognition-ensemble"


def test_failed_visual_mrp_fallback_does_not_invent_reference_evidence():
    engine = DirectRecognitionTargetedEngine()
    engine.recognize_text_line = lambda raw: OCRResult(  # type: ignore[method-assign]
        text="",
        engine=engine.name,
        width=1000,
        height=220,
    )

    outcome = recover_referenced_declarations(
        HANDHELD_FIXTURE.read_bytes(),
        "Mfg. By: Nestle India Limited\nNET QUANTITY:",
        existing_declarations=[],
        engine=engine,
    )

    declarations = _declaration_map(outcome.declarations)
    assert "mrp" not in declarations
    assert "mrp_reference" not in declarations
    assert outcome.traces[0].resolved is False
    assert "searched the visually detected seal/crimp region" in outcome.traces[0].message


def test_mrp_candidate_parser_prefers_retail_price_over_parenthesized_unit_rate():
    # Captured verbatim from the real PP-OCRv6 direct-recognition run. The
    # variable-print line contains the retail price first and a parenthesized
    # unit sale price second. The latter must never win merely because its
    # ``Rs`` token was recognized more cleanly.
    samples = [
        "Re 60(Rs.0.21 Per 9)-61839939CA-JUL/26-M0R/27.02.",
        "e 60(Rs.0.21 per 9)-61839939CA-JUL/26-MPR127.022",
        "60(Rs.0.21 Per 9)-61839939CA-JUL/26-MAR127.022",
        "Re.60(Rs.0.21 per 9)-61",
        "Ra.60(Rs.0.21 per 9)-61",
    ]

    for sample in samples:
        parsed = _parse_currency_value(sample)
        assert parsed is not None
        assert parsed[0] == "INR"
        assert parsed[1] == "60"


def test_mrp_candidate_parser_rejects_standalone_unit_sale_price_as_mrp():
    assert _parse_currency_value("Rs.0.21 per g") is None
    assert _parse_currency_value("R5 0.21 Per 9") is None


def test_mrp_candidate_parser_still_accepts_simple_currency_amount():
    assert _parse_currency_value("Rs 60/-")[:2] == ("INR", "60")
    assert _parse_currency_value("Re. 60")[:2] == ("INR", "60")

EXIF_ROTATED_FIXTURE = (
    Path(__file__).parent / "fixtures" / "maggi-mrp-under-seal-exif-rotated.jpeg"
)


def test_exif_rotated_fixture_is_normalized_before_computer_vision():
    from app.vision.preprocessing import image_from_bytes

    image = image_from_bytes(EXIF_ROTATED_FIXTURE.read_bytes())

    # The JPEG stores portrait pixel dimensions (902x1600) with EXIF
    # Orientation=6. The visual/package orientation is landscape (1600x902).
    assert image.shape == (902, 1600, 3)


def test_exif_rotated_fixture_seal_detector_finds_visual_black_strip():
    candidates = find_target_crops(EXIF_ROTATED_FIXTURE.read_bytes(), "seal")

    assert candidates
    strongest = candidates[0]
    assert strongest.label.startswith("seal-row-")
    assert strongest.score >= 1.0
    assert strongest.width >= 0.85 * 1600
    assert 0.30 * 902 <= strongest.y <= 0.50 * 902
    assert strongest.height <= 0.16 * 902


def test_exif_rotated_live_photo_can_trigger_visual_mrp_fallback():
    engine = DirectRecognitionTargetedEngine()
    primary_text = """
    NESTLE CONSUMER CARE
    Mfg. By: Nestle India Limited
    Lot No.-MFD.-USE BY:
    NET QUANTITY:
    """

    outcome = recover_referenced_declarations(
        EXIF_ROTATED_FIXTURE.read_bytes(),
        primary_text,
        existing_declarations=[],
        engine=engine,
    )

    declarations = _declaration_map(outcome.declarations)
    assert declarations["mrp"].value == "INR 60"
    assert declarations["mrp"].attributes["source"] == "required_mrp_visual_fallback"
    assert outcome.traces[0].resolved is True
    assert outcome.traces[0].strategy == "direct-text-recognition-ensemble"
