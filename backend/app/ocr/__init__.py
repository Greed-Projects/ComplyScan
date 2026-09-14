from .base import OCRResult, OCRTextRegion, OcrEngine
from .paddle_onnx_engine import PaddleOcrOnnxEngine, get_ocr_engine

__all__ = [
    "OCRResult",
    "OCRTextRegion",
    "OcrEngine",
    "PaddleOcrOnnxEngine",
    "get_ocr_engine",
]
