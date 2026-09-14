from app.inspection import merge_image_declarations
from app.models import (
    ExtractedDeclaration,
    ImageMetadata,
    PackageImageAnalysis,
)
from app.rules import evaluate_declarations


def _image(image_id: str, *declarations: ExtractedDeclaration) -> PackageImageAnalysis:
    return PackageImageAnalysis(
        image_id=image_id,
        file_name=f"{image_id}.jpg",
        ocr_engine="test",
        ocr_text="test image text long enough for deterministic evaluation",
        image=ImageMetadata(width=1000, height=700),
        declarations=list(declarations),
    )


def _declaration(
    key: str,
    value: str,
    image_id: str,
    **attributes: str,
) -> ExtractedDeclaration:
    return ExtractedDeclaration(
        key=key,
        label=key.replace("_", " ").title(),
        value=value,
        evidence=value,
        confidence=0.92,
        attributes={**attributes, "source_file": f"{image_id}.jpg"},
        source_image_ids=[image_id],
    )


def test_equivalent_mrp_formatting_across_images_confirms_instead_of_conflicts():
    first = _declaration("mrp", "INR 60", "image-1", amount="60", currency="INR", tax_inclusive_phrase="true")
    second = _declaration("mrp", "INR 60.00", "image-2", amount="60.00", currency="INR", tax_inclusive_phrase="true")

    merged = merge_image_declarations([_image("image-1", first), _image("image-2", second)])
    mrp = next(item for item in merged if item.key == "mrp")

    assert mrp.attributes["multi_image_confirmed"] == "true"
    assert "multi_image_conflict" not in mrp.attributes
    assert mrp.source_image_ids == ["image-1", "image-2"]


def test_consumer_care_attributes_can_be_fused_across_package_views():
    first = _declaration(
        "consumer_care",
        "9876543210",
        "image-1",
        phone="9876543210",
        address_detected="true",
    )
    second = _declaration(
        "consumer_care",
        "care@example.com",
        "image-2",
        email="care@example.com",
        address_detected="false",
    )

    merged = merge_image_declarations([_image("image-1", first), _image("image-2", second)])
    care = next(item for item in merged if item.key == "consumer_care")

    assert care.attributes["phone"] == "9876543210"
    assert care.attributes["email"] == "care@example.com"
    assert care.attributes["address_detected"] == "true"
    assert care.source_image_ids == ["image-1", "image-2"]


def test_conflicting_net_quantities_do_not_trigger_small_package_exemption():
    small = _declaration("net_quantity", "10 g", "image-1", amount="10", unit="g")
    large = _declaration("net_quantity", "200 g", "image-2", amount="200", unit="g")
    merged = merge_image_declarations([_image("image-1", small), _image("image-2", large)])

    checks, summary = evaluate_declarations(
        "combined package OCR text with enough content to evaluate required declarations safely",
        merged,
    )
    net_quantity = next(check for check in checks if check.key == "net_quantity")

    assert net_quantity.status == "warning"
    assert summary.status != "not_applicable"
    assert "Conflicting values" in net_quantity.message
