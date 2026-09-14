from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import sys
import warnings
from pathlib import Path


EXPECTED = {
    "paddleocr": "3.7.0",
    "paddlex": "3.7.2",
    "onnxruntime": "1.29.0",
    "opencv-contrib-python": "4.10.0.84",
    "numpy": "2.3.5",
}

MODEL_DIRECTORY_NAMES = (
    "PP-OCRv6_medium_det_onnx",
    "PP-OCRv6_medium_rec_onnx",
)


def version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "NOT INSTALLED"


def require_version(name: str, expected: str) -> bool:
    actual = version(name)
    print(f"{name:22} {actual}")

    if actual != expected:
        print(f"ERROR: expected {name}=={expected}, found {actual}.")
        return False

    return True


def model_cache_status() -> tuple[Path, list[str]]:
    model_root = Path.home() / ".paddlex" / "official_models"

    missing_models = [
        model_name
        for model_name in MODEL_DIRECTORY_NAMES
        if not (model_root / model_name).is_dir()
    ]

    return model_root, missing_models


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify PackCheck OCR runtime.")
    parser.add_argument(
        "--warmup-image",
        type=Path,
        help="Optional image used to initialize OCR models and run one scan.",
    )
    args = parser.parse_args()

    warnings.simplefilter("error", DeprecationWarning)
    warnings.simplefilter("error", FutureWarning)

    print(f"Python:                 {sys.version.split()[0]}")
    print("Deprecation policy:     DeprecationWarning/FutureWarning => ERROR")

    if sys.version_info[:2] != (3, 13):
        print("ERROR: PackCheck is validated for CPython 3.13.x only.")
        return 1

    versions_ok = True

    for name, expected in EXPECTED.items():
        versions_ok = require_version(name, expected) and versions_ok

    paddle_version = version("paddlepaddle")
    paddle_module = importlib.util.find_spec("paddle")

    if paddle_version != "NOT INSTALLED" or paddle_module is not None:
        print(
            "ERROR: PaddlePaddle is present. "
            "This prototype must use ONNX Runtime only."
        )
        return 2

    if not versions_ok:
        return 3

    try:
        import onnxruntime as ort
    except ImportError as exc:
        print(f"ERROR: cannot import onnxruntime: {exc}")
        return 4

    providers = ort.get_available_providers()
    print(f"Available providers:    {providers}")

    if "CPUExecutionProvider" not in providers:
        print("ERROR: CPUExecutionProvider is unavailable.")
        return 5

    print("Portable CPU provider:  OK")

    if args.warmup_image is not None:
        image = args.warmup_image.resolve()

        if not image.is_file():
            print(f"ERROR: warm-up image does not exist: {image}")
            return 6

        root = Path(__file__).resolve().parents[1]

        if str(root) not in sys.path:
            sys.path.insert(0, str(root))

        from app.ocr.paddle_onnx_engine import PaddleOcrOnnxEngine

        print("\nInitializing PP-OCRv6 medium ONNX models...")

        model_root, missing_models = model_cache_status()

        if missing_models:
            print("OCR model cache is incomplete; missing models will be downloaded.")
            print(f"Model cache:             {model_root}")
            print(f"Missing models:          {', '.join(missing_models)}")

        engine = PaddleOcrOnnxEngine()
        result = engine.extract(image.read_bytes())

        print(f"Engine:                 {result.engine}")
        print(f"Image:                  {result.width}x{result.height}")
        print(f"Detected regions:       {len(result.regions)}")

        if not result.regions:
            print("ERROR: OCR warm-up completed but no text regions were detected.")
            return 7

        print("OCR warm-up:            OK")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())