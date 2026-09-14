import sys
import types

import pytest

from app.ocr.paddle_onnx_engine import PaddleOcrOnnxEngine


def test_paddle_payload_is_normalized_to_regions():
    payload = {
        "rec_texts": ["MRP: Rs. 99.00", "Net Quantity: 200 g"],
        "rec_scores": [0.98, 0.91],
        "rec_polys": [
            [[10, 20], [210, 20], [210, 60], [10, 60]],
            [[20, 100], [240, 100], [240, 145], [20, 145]],
        ],
    }
    regions = PaddleOcrOnnxEngine._regions_from_payload(
        payload, width=400, height=200
    )

    assert len(regions) == 2
    assert regions[0].text == "MRP: Rs. 99.00"
    assert regions[0].confidence == 0.98
    assert regions[0].polygon[0] == (0.025, 0.1)
    assert regions[1].bbox == pytest.approx((0.05, 0.5, 0.55, 0.225))


def test_medium_models_are_fixed_for_the_stable_prototype_profile():
    assert PaddleOcrOnnxEngine.DETECTION_MODEL == "PP-OCRv6_medium_det"
    assert PaddleOcrOnnxEngine.RECOGNITION_MODEL == "PP-OCRv6_medium_rec"
    assert "ONNX Runtime" in PaddleOcrOnnxEngine().name


def test_pipeline_explicitly_uses_onnx_cpu_and_supported_orientation_options(monkeypatch):
    captured: dict[str, object] = {}

    fake_ort = types.ModuleType("onnxruntime")
    fake_ort.get_available_providers = lambda: ["CPUExecutionProvider"]

    class FakePaddleOCR:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    fake_paddleocr = types.ModuleType("paddleocr")
    fake_paddleocr.PaddleOCR = FakePaddleOCR

    monkeypatch.setitem(sys.modules, "onnxruntime", fake_ort)
    monkeypatch.setitem(sys.modules, "paddleocr", fake_paddleocr)

    engine = PaddleOcrOnnxEngine()
    engine._get_pipeline()

    assert captured == {
        "text_detection_model_name": "PP-OCRv6_medium_det",
        "text_recognition_model_name": "PP-OCRv6_medium_rec",
        "engine": "onnxruntime",
        "device": "cpu",
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_textline_orientation": False,
    }


def test_direct_recognizer_explicitly_uses_same_ppocrv6_onnx_model(monkeypatch):
    captured: dict[str, object] = {}

    fake_ort = types.ModuleType("onnxruntime")
    fake_ort.get_available_providers = lambda: ["CPUExecutionProvider"]

    class FakeTextRecognition:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    fake_paddleocr = types.ModuleType("paddleocr")
    fake_paddleocr.TextRecognition = FakeTextRecognition

    monkeypatch.setitem(sys.modules, "onnxruntime", fake_ort)
    monkeypatch.setitem(sys.modules, "paddleocr", fake_paddleocr)

    engine = PaddleOcrOnnxEngine()
    engine._get_text_recognizer()

    assert captured == {
        "model_name": "PP-OCRv6_medium_rec",
        "engine": "onnxruntime",
        "device": "cpu",
    }


def test_extract_normalizes_exif_orientation_before_ocr(monkeypatch):
    from pathlib import Path
    from PIL import Image

    fixture = (
        Path(__file__).parent
        / "fixtures"
        / "maggi-mrp-under-seal-exif-rotated.jpeg"
    )
    observed: dict[str, tuple[int, int]] = {}

    class FakePipeline:
        def predict(self, image_path: str):
            with Image.open(image_path) as image:
                observed["size"] = image.size
            return []

    engine = PaddleOcrOnnxEngine()
    monkeypatch.setattr(engine, "_get_pipeline", lambda: FakePipeline())

    result = engine.extract(fixture.read_bytes())

    assert (result.width, result.height) == (1600, 902)
    assert observed["size"] == (1600, 902)
