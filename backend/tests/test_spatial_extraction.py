import random

import pytest

from app.extraction import extract_declarations
from app.models import OcrRegion


def region(
    region_id: str,
    text: str,
    bbox: list[float],
    confidence: float = 0.95,
) -> OcrRegion:
    x, y, width, height = bbox
    return OcrRegion(
        id=region_id,
        text=text,
        confidence=confidence,
        bbox=bbox,
        polygon=[
            {"x": x, "y": y},
            {"x": x + width, "y": y},
            {"x": x + width, "y": y + height},
            {"x": x, "y": y + height},
        ],
    )


@pytest.mark.parametrize("seed", range(6))
def test_sattu_landscape_priority_fields_use_geometry_not_serialization_order(seed):
    regions = [
        region("nutrition-carb", "58.86g", [0.49, 0.48, 0.06, 0.02], 0.99),
        region("nutrition-protein", "23.97g", [0.51, 0.51, 0.06, 0.02], 0.98),
        region("net-label", "Net Wt.", [0.3326, 0.5819, 0.0621, 0.0131], 0.945),
        region("month-label", "MTH.OF PACK", [0.4678, 0.5788, 0.0776, 0.0156], 0.916),
        region("mrp-label", "M.R.PRs", [0.5732, 0.5806, 0.0588, 0.0113], 0.955),
        region("barcode", "81908008806049", [0.1630, 0.5888, 0.0266, 0.0975], 0.975),
        region("net-value", "500g.", [0.3304, 0.5956, 0.0721, 0.0200], 0.999),
        region("lot-value", "B/1", [0.4368, 0.6019, 0.0266, 0.0137], 0.67),
        region("month-value", "AUGUST/2026", [0.4767, 0.6006, 0.0831, 0.0131], 0.956),
        region("mrp-noise", "00", [0.6131, 0.6006, 0.0233, 0.0150], 0.77),
    ]
    random.Random(seed).shuffle(regions)

    text = "\n".join(item.text for item in regions)
    declarations = {item.key: item for item in extract_declarations(text, regions)}

    assert declarations["net_quantity"].value == "500 g"
    assert declarations["net_quantity"].attributes["amount"] == "500"
    assert declarations["net_quantity"].attributes["extraction_strategy"] == (
        "spatial_label_value"
    )
    assert set(declarations["net_quantity"].region_ids) == {"net-label", "net-value"}

    assert declarations["month_year"].value == "08/2026"
    assert declarations["month_year"].attributes["month"] == "08"
    assert declarations["month_year"].attributes["year"] == "2026"
    assert set(declarations["month_year"].region_ids) == {
        "month-label",
        "month-value",
    }

    # The 14-digit barcode must never be promoted to MRP merely because OCR
    # serialized it after the MRP label.
    assert "mrp" not in declarations


def test_sattu_portrait_tolerates_ne_w_ocr_label_for_net_weight():
    regions = [
        region("nutrition", "23.97g", [0.15, 0.46, 0.06, 0.02], 0.98),
        region("net-label", "Ne W", [0.5521, 0.5356, 0.0277, 0.0394], 0.835),
        region("net-value", "500g.", [0.5754, 0.5300, 0.0455, 0.0469], 0.988),
    ]

    declarations = {item.key: item for item in extract_declarations(
        "23.97g\nNe W\n500g.",
        regions,
    )}

    assert declarations["net_quantity"].value == "500 g"
    assert set(declarations["net_quantity"].region_ids) == {
        "net-label",
        "net-value",
    }


def test_unlabelled_nutrition_value_is_not_inferred_as_net_quantity():
    declarations = {
        item.key: item
        for item in extract_declarations(
            "Nutritional Information Per 100g\nCarbohydrate\n58.86g\nProtein\n23.97g"
        )
    }

    assert "net_quantity" not in declarations


def test_text_mrp_does_not_cross_newline_into_barcode():
    declarations = {
        item.key: item
        for item in extract_declarations("M.R.PRs\n81908008806049")
    }

    assert "mrp" not in declarations


def test_spatial_mrp_prefers_nearby_price_and_rejects_far_barcode():
    regions = [
        region("mrp-label", "MRP Rs.", [0.50, 0.50, 0.09, 0.025], 0.98),
        region("mrp-value", "60.00", [0.51, 0.535, 0.06, 0.025], 0.97),
        region("tax", "Inclusive of all taxes", [0.60, 0.50, 0.15, 0.025], 0.94),
        region("barcode", "81908008806049", [0.08, 0.54, 0.10, 0.025], 0.99),
    ]

    declarations = {item.key: item for item in extract_declarations(
        "MRP Rs.\n60.00\nInclusive of all taxes\n81908008806049",
        regions,
    )}

    mrp = declarations["mrp"]
    assert mrp.value == "INR 60.00"
    assert mrp.attributes["amount"] == "60.00"
    assert mrp.attributes["currency"] == "INR"
    assert mrp.attributes["tax_inclusive_phrase"] == "true"
    assert set(mrp.region_ids) == {"mrp-label", "mrp-value"}
