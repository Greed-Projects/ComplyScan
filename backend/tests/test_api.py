import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


DEMO = (
    "Product Name: Roasted Peanuts\n"
    "Manufactured by: Innovate Foods Pvt Ltd, Sector 62, Noida, Uttar Pradesh 201309\n"
    "Net Quantity: 200 g\n"
    "MRP: Rs. 99.00 Inclusive of all taxes\n"
    "Mfg Date: 08/2026\n"
    "Consumer Care: Innovate Foods Pvt Ltd, Sector 62, Noida 201309 | care@example.com | 9876543210\n"
    "Unit Sale Price: Rs 0.50 / g"
)


@pytest.mark.anyio
async def test_manual_text_analysis_does_not_require_ocr_runtime():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post("/api/analyze", data={"override_text": DEMO})

    assert response.status_code == 200
    payload = response.json()

    assert payload["input_mode"] == "manual_text"
    assert payload["image_count"] == 0
    assert payload["images"] == []
    assert payload["summary"]["failed"] == 0
    assert payload["ruleset"] == "india-lmpc-retail-package-2026-05-29-v1"
    assert payload["rule_profile"]["checked_through"] == "2026-09-13"
    assert payload["context"]["imported_product"] is False


@pytest.mark.anyio
async def test_api_context_changes_rule_applicability():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/analyze",
            data={"override_text": DEMO, "imported_product": "true"},
        )

    assert response.status_code == 200
    payload = response.json()
    country = next(check for check in payload["checks"] if check["key"] == "country_origin")
    assert country["applicability"] == "required"
    assert country["status"] == "fail"


@pytest.mark.anyio
async def test_image_analysis_resolves_referenced_mrp_with_targeted_ocr(monkeypatch):
    from pathlib import Path

    import app.main as main_module
    from app.ocr.base import OCRResult, OCRTextRegion

    fixture = Path(__file__).resolve().parents[2] / "samples" / "maggi-mrp-under-seal.jpeg"

    class FakeImageEngine:
        def __init__(self) -> None:
            self.calls = 0

        @property
        def name(self) -> str:
            return "fake-image-engine"

        def extract(self, raw: bytes) -> OCRResult:
            self.calls += 1
            if self.calls == 1:
                text = (
                    "Product Name: Noodles\n"
                    "Manufactured by: Example Foods Pvt Ltd, New Delhi 110001\n"
                    "Net Quantity: 280 g\n"
                    "For MRP (incl. of all taxes): See under the seal\n"
                    "Consumer Care: Example Foods, New Delhi 110001 | care@example.com | 9876543210"
                )
                return OCRResult(
                    text=text,
                    engine=self.name,
                    width=1600,
                    height=902,
                    regions=(
                        OCRTextRegion(
                            id="r1",
                            text="For MRP (incl. of all taxes): See under the seal",
                            confidence=0.94,
                            polygon=((0.08, 0.50), (0.52, 0.50), (0.52, 0.56), (0.08, 0.56)),
                        ),
                    ),
                )

            return OCRResult(
                text="Rs 60/-",
                engine=self.name,
                width=1000,
                height=200,
                regions=(
                    OCRTextRegion(
                        id="r1",
                        text="Rs 60/-",
                        confidence=0.92,
                        polygon=((0.2, 0.3), (0.4, 0.3), (0.4, 0.6), (0.2, 0.6)),
                    ),
                ),
            )

    fake_engine = FakeImageEngine()
    monkeypatch.setattr(main_module, "get_ocr_engine", lambda: fake_engine)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/analyze",
            files=[("files", ("package.jpeg", fixture.read_bytes(), "image/jpeg"))],
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["input_mode"] == "images"
    assert payload["image_count"] == 1
    image = payload["images"][0]
    mrp = next(item for item in payload["declarations"] if item["key"] == "mrp")

    assert mrp["value"] == "INR 60"
    assert mrp["attributes"]["source"] == "referenced_region_ensemble"
    assert mrp["source_image_ids"] == ["image-1"]
    assert image["ocr_recovery"][0]["resolved"] is True
    assert any(region["source"].startswith("ensemble:seal:") for region in image["regions"])
    assert all(region["id"].startswith("image-1:") for region in image["regions"])


@pytest.mark.anyio
async def test_multiple_images_fuse_complementary_declarations(monkeypatch):
    import app.main as main_module
    from app.ocr.base import OCRResult

    front = (
        "Product Name: Roasted Peanuts\n"
        "Net Quantity: 200 g\n"
        "MRP: Rs. 99.00 Inclusive of all taxes\n"
        "Mfg Date: 08/2026"
    )
    back = (
        "Manufactured by: Innovate Foods Pvt Ltd, Sector 62, Noida, Uttar Pradesh 201309\n"
        "Consumer Care: Innovate Foods Pvt Ltd, Sector 62, Noida 201309 | care@example.com | 9876543210\n"
        "Unit Sale Price: Rs 0.50 / g"
    )

    class FakeEngine:
        @property
        def name(self) -> str:
            return "fake-multi-image"

        def extract(self, raw: bytes) -> OCRResult:
            text = front if raw == b"front" else back
            return OCRResult(text=text, engine=self.name, width=1200, height=800)

    monkeypatch.setattr(main_module, "get_ocr_engine", lambda: FakeEngine())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/analyze",
            files=[
                ("files", ("front.jpg", b"front", "image/jpeg")),
                ("files", ("back.jpg", b"back", "image/jpeg")),
            ],
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["image_count"] == 2
    assert payload["file_names"] == ["front.jpg", "back.jpg"]
    assert payload["summary"]["failed"] == 0

    keyed = {item["key"]: item for item in payload["declarations"]}
    assert keyed["mrp"]["source_image_ids"] == ["image-1"]
    assert keyed["manufacturer"]["source_image_ids"] == ["image-2"]
    assert keyed["unit_sale_price"]["source_image_ids"] == ["image-2"]


@pytest.mark.anyio
async def test_conflicting_values_across_images_are_review_not_silent_pass(monkeypatch):
    import app.main as main_module
    from app.ocr.base import OCRResult

    text_a = DEMO
    text_b = DEMO.replace("MRP: Rs. 99.00", "MRP: Rs. 109.00")

    class FakeEngine:
        @property
        def name(self) -> str:
            return "fake-conflict"

        def extract(self, raw: bytes) -> OCRResult:
            text = text_a if raw == b"a" else text_b
            return OCRResult(text=text, engine=self.name, width=1000, height=700)

    monkeypatch.setattr(main_module, "get_ocr_engine", lambda: FakeEngine())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/analyze",
            files=[
                ("files", ("side-a.jpg", b"a", "image/jpeg")),
                ("files", ("side-b.jpg", b"b", "image/jpeg")),
            ],
        )

    assert response.status_code == 200
    payload = response.json()
    mrp = next(item for item in payload["checks"] if item["key"] == "mrp")
    declaration = next(item for item in payload["declarations"] if item["key"] == "mrp")

    assert mrp["status"] == "warning"
    assert "Conflicting values" in mrp["message"]
    assert declaration["attributes"]["multi_image_conflict"] == "true"
    assert set(declaration["source_image_ids"]) == {"image-1", "image-2"}


@pytest.mark.anyio
async def test_per_image_analysis_and_json_fusion_match_multi_image_contract(monkeypatch):
    import app.main as main_module
    from app.ocr.base import OCRResult

    front = (
        "Product Name: Roasted Peanuts\n"
        "Net Quantity: 200 g\n"
        "MRP: Rs. 99.00 Inclusive of all taxes\n"
        "Mfg Date: 08/2026"
    )
    back = (
        "Manufactured by: Innovate Foods Pvt Ltd, Sector 62, Noida, Uttar Pradesh 201309\n"
        "Consumer Care: Innovate Foods Pvt Ltd, Sector 62, Noida 201309 | care@example.com | 9876543210\n"
        "Unit Sale Price: Rs 0.50 / g"
    )

    class FakeEngine:
        @property
        def name(self) -> str:
            return "fake-deployment-transport"

        def extract(self, raw: bytes) -> OCRResult:
            text = front if raw == b"front" else back
            return OCRResult(text=text, engine=self.name, width=1200, height=800)

    monkeypatch.setattr(main_module, "get_ocr_engine", lambda: FakeEngine())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        image_payloads = []
        for index, (name, raw) in enumerate(
            (("front.jpg", b"front"), ("back.jpg", b"back")),
            start=1,
        ):
            response = await client.post(
                "/api/analyze/image",
                data={"image_id": f"image-{index}"},
                files={"file": (name, raw, "image/jpeg")},
            )
            assert response.status_code == 200
            payload = response.json()
            image_payloads.append(
                {
                    "image_id": payload["image_id"],
                    "file_name": payload["file_name"],
                    "ocr_text": payload["ocr_text"],
                    "declarations": payload["declarations"],
                }
            )

        response = await client.post(
            "/api/analyze/fuse",
            json={
                "images": image_payloads,
                "context": {
                    "imported_product": False,
                    "may_become_unfit_for_human_consumption": False,
                    "dimensions_relevant": False,
                    "package_form": "single",
                    "alcoholic_beverage": False,
                    "commodity_class": "general",
                },
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["image_count"] == 2
    assert payload["file_names"] == ["front.jpg", "back.jpg"]
    assert payload["images"] == []
    assert payload["summary"]["failed"] == 0

    keyed = {item["key"]: item for item in payload["declarations"]}
    assert keyed["mrp"]["source_image_ids"] == ["image-1"]
    assert keyed["manufacturer"]["source_image_ids"] == ["image-2"]


@pytest.mark.anyio
async def test_per_image_endpoint_rejects_invalid_image_id(monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/analyze/image",
            data={"image_id": "../image-1"},
            files={"file": ("front.jpg", b"front", "image/jpeg")},
        )

    assert response.status_code == 400
    assert "image_id" in response.json()["detail"]
