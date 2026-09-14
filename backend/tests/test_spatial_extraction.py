import random

import pytest

from app.extraction import extract_declarations
from app.models import OcrRegion


def region(
    region_id: str,
    text: str,
    bbox: list[float],
    confidence: float,
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


def sattu_landscape_regions() -> list[OcrRegion]:
    """Exact critical OCR regions recorded from Sattu Landscape.jpeg."""

    return [
        region(
            "image-1:r31",
            "58.86g",
            [
                0.4933481152993348,
                0.436875,
                0.019955654101995568,
                0.029374999999999984,
            ],
            0.9198039174079895,
        ),
        region(
            "image-1:r39",
            "Net Wt.",
            [
                0.3325942350332594,
                0.581875,
                0.062084257206208415,
                0.013124999999999942,
            ],
            0.9454150795936584,
        ),
        region(
            "image-1:r40",
            "Lot No.",
            [
                0.4090909090909091,
                0.5825,
                0.04212860310421285,
                0.011874999999999969,
            ],
            0.9252004623413086,
        ),
        region(
            "image-1:r41",
            "MTH.OF PACK",
            [
                0.4678492239467849,
                0.57875,
                0.0776053215077605,
                0.015625,
            ],
            0.9161772131919861,
        ),
        region(
            "image-1:r42",
            "M.R.PRs",
            [
                0.573170731707317,
                0.580625,
                0.058758314855875904,
                0.011250000000000093,
            ],
            0.9553483128547668,
        ),
        region(
            "image-1:r43",
            "81908008806049",
            [
                0.1629711751662971,
                0.58875,
                0.026607538802660757,
                0.09750000000000003,
            ],
            0.975283682346344,
        ),
        region(
            "image-1:r44",
            "500g.",
            [
                0.3303769401330377,
                0.595625,
                0.07206208425720623,
                0.020000000000000018,
            ],
            0.9999771118164062,
        ),
        region(
            "image-1:r46",
            "B/1",
            [
                0.43680709534368073,
                0.601875,
                0.026607538802660757,
                0.013749999999999929,
            ],
            0.670083224773407,
        ),
        region(
            "image-1:r47",
            "AUGUST/2026",
            [
                0.47671840354767187,
                0.600625,
                0.08314855875831478,
                0.013125000000000053,
            ],
            0.9557490944862366,
        ),
        region(
            "image-1:r49",
            "00",
            [
                0.6130820399113082,
                0.600625,
                0.02328159645232819,
                0.015000000000000013,
            ],
            0.772793710231781,
        ),
    ]


def sattu_portrait_regions() -> list[OcrRegion]:
    """Exact critical OCR regions recorded from Sattu Portrait.jpeg."""

    return [
        region(
            "image-1:r19",
            "AGusT/au26",
            [
                0.5931263858093127,
                0.430625,
                0.026607538802660757,
                0.05625000000000002,
            ],
            0.7769055366516113,
        ),
        region(
            "image-1:r22",
            "23.97g",
            [
                0.27605321507760533,
                0.450625,
                0.058758314855875904,
                0.013125000000000053,
            ],
            0.8941797614097595,
        ),
        region(
            "image-1:r38",
            "5.12g",
            [
                0.2860310421286031,
                0.52125,
                0.04545454545454547,
                0.011249999999999982,
            ],
            0.949975311756134,
        ),
        region(
            "image-1:r39",
            "Ne W",
            [
                0.5521064301552107,
                0.535625,
                0.027716186252771613,
                0.03937499999999994,
            ],
            0.8348160982131958,
        ),
        region(
            "image-1:r40",
            "500g.",
            [
                0.5753880266075388,
                0.53,
                0.045454545454545414,
                0.046875,
            ],
            0.9880223274230957,
        ),
    ]


@pytest.mark.parametrize("seed", range(8))
def test_real_sattu_landscape_geometry_not_serialization_order(seed):
    regions = sattu_landscape_regions()
    random.Random(seed).shuffle(regions)

    text = "\n".join(item.text for item in regions)
    declarations = {item.key: item for item in extract_declarations(text, regions)}

    net_quantity = declarations["net_quantity"]
    assert net_quantity.value == "500 g"
    assert net_quantity.attributes["amount"] == "500"
    assert net_quantity.attributes["unit"] == "g"
    assert net_quantity.attributes["extraction_strategy"] == "spatial_label_value"
    assert set(net_quantity.region_ids) == {"image-1:r39", "image-1:r44"}

    month_year = declarations["month_year"]
    assert month_year.value == "08/2026"
    assert month_year.attributes["month"] == "08"
    assert month_year.attributes["year"] == "2026"
    assert month_year.attributes["extraction_strategy"] == "spatial_label_value"
    assert set(month_year.region_ids) == {"image-1:r41", "image-1:r47"}

    # The recorded 14-digit barcode is geometrically far from the MRP label and
    # is also outside the plausible MRP numeric shape. It must never be promoted.
    assert "mrp" not in declarations


@pytest.mark.parametrize("seed", range(8))
def test_real_sattu_portrait_geometry_recovers_500g_not_nutrition(seed):
    regions = sattu_portrait_regions()
    random.Random(seed).shuffle(regions)

    text = "\n".join(item.text for item in regions)
    declarations = {item.key: item for item in extract_declarations(text, regions)}

    net_quantity = declarations["net_quantity"]
    assert net_quantity.value == "500 g"
    assert set(net_quantity.region_ids) == {"image-1:r39", "image-1:r40"}

    # The portrait OCR contains a damaged-looking "AGusT/au26" region but no
    # reliable packing/manufacturing label anchor. Do not invent a legal date.
    assert "month_year" not in declarations
    assert "mrp" not in declarations


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

    declarations = {
        item.key: item
        for item in extract_declarations(
            "MRP Rs.\n60.00\nInclusive of all taxes\n81908008806049",
            regions,
        )
    }

    mrp = declarations["mrp"]
    assert mrp.value == "INR 60.00"
    assert mrp.attributes["amount"] == "60.00"
    assert mrp.attributes["currency"] == "INR"
    assert mrp.attributes["tax_inclusive_phrase"] == "true"
    assert set(mrp.region_ids) == {"mrp-label", "mrp-value"}
