from app.analyzer import analyze_text
from app.models import OcrRegion, PackageContext, Point


COMPLETE_TEXT = """
Product Name: Roasted Peanuts
Manufactured by: Innovate Foods Pvt Ltd, Sector 62, Noida, Uttar Pradesh 201309
Net Quantity: 200 g
MRP: Rs. 99.00 Inclusive of all taxes
Mfg Date: 08/2026
Consumer Care: Innovate Foods Pvt Ltd, Sector 62, Noida 201309 | care@innovatefoods.example | 9876543210
Unit Sale Price: Rs 0.50 / g
"""


def _by_key(checks):
    return {check.key: check for check in checks}


def test_complete_general_label_scores_high():
    checks, summary = analyze_text(COMPLETE_TEXT)
    keyed = _by_key(checks)

    assert summary.score is not None and summary.score >= 95
    assert summary.failed == 0
    assert keyed["mrp"].status == "pass"
    assert keyed["unit_sale_price"].status == "pass"
    assert keyed["country_origin"].status == "not_applicable"
    assert keyed["best_before"].status == "not_applicable"
    assert keyed["dimensions"].status == "not_applicable"


def test_missing_core_fields_are_flagged():
    text = "Tasty Snack\nKeep in a cool dry place\nBatch A102 with enough text for rule evaluation"
    checks, summary = analyze_text(text)
    assert summary.status in {"warning", "fail"}
    assert _by_key(checks)["mrp"].status != "pass"


def test_detected_declaration_links_to_ocr_region():
    region = OcrRegion(
        id="r1",
        text="MRP: Rs. 99.00 Inclusive of all taxes",
        confidence=0.97,
        polygon=[
            Point(x=0.1, y=0.1),
            Point(x=0.7, y=0.1),
            Point(x=0.7, y=0.2),
            Point(x=0.1, y=0.2),
        ],
        bbox=[0.1, 0.1, 0.6, 0.1],
    )
    checks, _ = analyze_text(region.text, [region])
    mrp = _by_key(checks)["mrp"]
    assert mrp.status == "pass"
    assert mrp.region_ids == ["r1"]


def test_mrp_preserves_currency_amount_and_tax_phrase():
    checks, _ = analyze_text("MRP: Rs. 99.00 Inclusive of all taxes")
    mrp = _by_key(checks)["mrp"]

    assert mrp.status == "pass"
    assert mrp.value == "INR 99.00"
    assert mrp.attributes == {
        "amount": "99.00",
        "tax_inclusive_phrase": "true",
        "currency": "INR",
    }


def test_mrp_without_currency_is_review_not_assumed_inr():
    text = COMPLETE_TEXT.replace("MRP: Rs. 99.00 Inclusive of all taxes", "MRP: 99.00 Inclusive of all taxes")
    checks, summary = analyze_text(text)
    mrp = _by_key(checks)["mrp"]

    assert mrp.status == "warning"
    assert mrp.value == "99.00"
    assert "currency" not in mrp.attributes
    assert "Indian-currency marker" in mrp.message
    assert summary.warnings >= 1


def test_mrp_without_tax_inclusive_wording_is_review():
    text = COMPLETE_TEXT.replace("MRP: Rs. 99.00 Inclusive of all taxes", "MRP: Rs. 99.00")
    checks, _ = analyze_text(text)
    mrp = _by_key(checks)["mrp"]

    assert mrp.status == "warning"
    assert mrp.attributes["tax_inclusive_phrase"] == "false"
    assert "inclusive of all taxes" in mrp.message


def test_unit_sale_price_wrong_denominator_is_a_failure():
    text = COMPLETE_TEXT.replace("Unit Sale Price: Rs 0.50 / g", "Unit Sale Price: Rs 49.50 / 100 g")
    checks, summary = analyze_text(text)
    usp = _by_key(checks)["unit_sale_price"]

    assert usp.status == "fail"
    assert "per-g basis" in usp.message
    assert summary.failed >= 1


def test_unit_sale_price_arithmetic_mismatch_is_a_failure():
    text = COMPLETE_TEXT.replace("Unit Sale Price: Rs 0.50 / g", "Unit Sale Price: Rs 0.40 / g")
    checks, _ = analyze_text(text)
    usp = _by_key(checks)["unit_sale_price"]

    assert usp.status == "fail"
    assert "Expected INR 0.50 per g" in usp.message


def test_combination_package_marks_unit_sale_price_not_applicable():
    context = PackageContext(package_form="combination")
    text = COMPLETE_TEXT.replace("Unit Sale Price: Rs 0.50 / g", "")
    checks, summary = analyze_text(text, context=context)
    usp = _by_key(checks)["unit_sale_price"]

    assert usp.status == "not_applicable"
    assert summary.failed == 0


def test_imported_product_requires_country_origin():
    context = PackageContext(imported_product=True)
    checks, summary = analyze_text(COMPLETE_TEXT, context=context)
    country = _by_key(checks)["country_origin"]

    assert country.applicability == "required"
    assert country.status == "fail"
    assert summary.failed >= 1


def test_imported_product_country_origin_passes_when_detected():
    context = PackageContext(imported_product=True)
    text = COMPLETE_TEXT + "\nCountry of Origin: Thailand"
    checks, _ = analyze_text(text, context=context)
    country = _by_key(checks)["country_origin"]

    assert country.status == "pass"
    assert country.value == "Thailand"
    assert country.legal_reference.endswith("Rule 6(1)(aa)")


def test_perishable_context_requires_best_before_or_use_by():
    context = PackageContext(may_become_unfit_for_human_consumption=True)
    checks, _ = analyze_text(COMPLETE_TEXT, context=context)
    best_before = _by_key(checks)["best_before"]
    assert best_before.status == "fail"

    checks, _ = analyze_text(COMPLETE_TEXT + "\nBest Before: 6 months from packing", context=context)
    assert _by_key(checks)["best_before"].status == "pass"


def test_dimensions_context_requires_dimension_declaration():
    context = PackageContext(dimensions_relevant=True)
    checks, _ = analyze_text(COMPLETE_TEXT, context=context)
    assert _by_key(checks)["dimensions"].status == "fail"

    checks, _ = analyze_text(COMPLETE_TEXT + "\nDimensions: 10 cm x 20 cm x 5 cm", context=context)
    assert _by_key(checks)["dimensions"].status == "pass"


def test_general_small_pack_is_outside_profile_under_rule_26_a():
    text = COMPLETE_TEXT.replace("Net Quantity: 200 g", "Net Quantity: 10 g")
    checks, summary = analyze_text(text)

    assert summary.status == "not_applicable"
    assert summary.score is None
    assert summary.not_applicable == len(checks)
    assert all(check.status == "not_applicable" for check in checks)


def test_pan_masala_small_pack_does_not_receive_general_small_pack_exemption():
    context = PackageContext(commodity_class="pan_masala")
    text = COMPLETE_TEXT.replace("Net Quantity: 200 g", "Net Quantity: 5 g")
    checks, summary = analyze_text(text, context=context)

    assert summary.status != "not_applicable"
    assert _by_key(checks)["mrp"].applicability == "required"


def test_mrp_dotted_abbreviation_is_supported():
    checks, _ = analyze_text("M.R.P. ₹ 149.50 inclusive of all taxes")
    mrp = _by_key(checks)["mrp"]

    assert mrp.status == "pass"
    assert mrp.attributes["currency"] == "INR"
    assert mrp.attributes["amount"] == "149.50"
