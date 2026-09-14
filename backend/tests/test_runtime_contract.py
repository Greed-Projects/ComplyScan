from pathlib import Path


def test_requirements_pin_onnx_runtime_and_exclude_paddlepaddle():
    requirements = (
        Path(__file__).resolve().parents[1] / "requirements.txt"
    ).read_text(encoding="utf-8").lower().splitlines()

    assert "onnxruntime==1.29.0" in requirements
    assert "paddleocr==3.7.0" in requirements
    assert "paddlex[ocr-core]==3.7.2" in requirements
    assert not any(line.startswith("paddlepaddle") for line in requirements)
