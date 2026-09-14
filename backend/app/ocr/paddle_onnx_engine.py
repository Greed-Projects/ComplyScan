from __future__ import annotations

import tempfile
import threading
import warnings
from pathlib import Path
from typing import Any

from ..vision.image_io import load_oriented_rgb_image
from .base import OCRResult, OCRTextRegion


class PaddleOcrOnnxEngine:
    """PP-OCRv6 medium models executed through ONNX Runtime on CPU.

    This is the application adapter only. Legal/compliance code consumes the
    normalized OCRResult contract and never depends on PaddleOCR/PaddleX result
    objects directly.
    """

    DETECTION_MODEL = "PP-OCRv6_medium_det"
    RECOGNITION_MODEL = "PP-OCRv6_medium_rec"

    def __init__(self) -> None:
        self._pipeline: Any | None = None
        self._recognizer: Any | None = None
        self._lock = threading.Lock()
        self._recognizer_lock = threading.Lock()

    @property
    def name(self) -> str:
        return "PaddleOCR 3.7 / PP-OCRv6 medium / ONNX Runtime (CPU)"

    def _get_pipeline(self) -> Any:
        if self._pipeline is not None:
            return self._pipeline

        with self._lock:
            if self._pipeline is not None:
                return self._pipeline

            try:
                import onnxruntime as ort
            except ImportError as exc:  # pragma: no cover - environment specific
                raise RuntimeError(
                    "ONNX Runtime is not installed. Run scripts/setup/bootstrap-windows.ps1."
                ) from exc

            available = ort.get_available_providers()
            if "CPUExecutionProvider" not in available:
                raise RuntimeError(
                    "ONNX Runtime CPUExecutionProvider is unavailable. "
                    f"Available providers: {available}"
                )

            try:
                from paddleocr import PaddleOCR
            except ImportError as exc:  # pragma: no cover - environment specific
                raise RuntimeError(
                    "PaddleOCR is not installed. Run scripts/setup/bootstrap-windows.ps1."
                ) from exc

            # This initialization matches the previously validated Windows design:
            # PP-OCRv6 medium detector/recognizer, no PaddlePaddle runtime, and
            # ONNX Runtime as the explicit inference engine. The document
            # orientation/unwarping/text-line orientation helper models are disabled
            # to keep the prototype deterministic and focused on package-label OCR.
            with warnings.catch_warnings():
                warnings.simplefilter("error", DeprecationWarning)
                warnings.simplefilter("error", FutureWarning)
                self._pipeline = PaddleOCR(
                    text_detection_model_name=self.DETECTION_MODEL,
                    text_recognition_model_name=self.RECOGNITION_MODEL,
                    engine="onnxruntime",
                    device="cpu",
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    use_textline_orientation=False,
                )
            return self._pipeline


    def _get_text_recognizer(self) -> Any:
        if self._recognizer is not None:
            return self._recognizer

        with self._recognizer_lock:
            if self._recognizer is not None:
                return self._recognizer

            try:
                import onnxruntime as ort
            except ImportError as exc:  # pragma: no cover - environment specific
                raise RuntimeError(
                    "ONNX Runtime is not installed. Run scripts/setup/bootstrap-windows.ps1."
                ) from exc

            available = ort.get_available_providers()
            if "CPUExecutionProvider" not in available:
                raise RuntimeError(
                    "ONNX Runtime CPUExecutionProvider is unavailable. "
                    f"Available providers: {available}"
                )

            try:
                from paddleocr import TextRecognition
            except ImportError as exc:  # pragma: no cover - environment specific
                raise RuntimeError(
                    "PaddleOCR is not installed. Run scripts/setup/bootstrap-windows.ps1."
                ) from exc

            # This module bypasses text detection. It is intentionally used only
            # after computer vision has localized a narrow text-line candidate.
            with warnings.catch_warnings():
                warnings.simplefilter("error", DeprecationWarning)
                warnings.simplefilter("error", FutureWarning)
                self._recognizer = TextRecognition(
                    model_name=self.RECOGNITION_MODEL,
                    engine="onnxruntime",
                    device="cpu",
                )
            return self._recognizer

    @staticmethod
    def _coerce_payload(result: Any) -> dict[str, Any]:
        payload = getattr(result, "json", None)
        if callable(payload):
            payload = payload()
        if isinstance(payload, dict):
            core = payload.get("res", payload)
            return core if isinstance(core, dict) else payload

        if isinstance(result, dict):
            core = result.get("res", result)
            return core if isinstance(core, dict) else result
        raise RuntimeError("PaddleOCR returned an unsupported result format.")

    @staticmethod
    def _normalise_polygon(
        polygon: Any,
        width: int,
        height: int,
    ) -> tuple[tuple[float, float], ...]:
        points: list[tuple[float, float]] = []
        if polygon is None:
            return tuple()
        for point in polygon:
            if len(point) < 2:
                continue
            x = min(1.0, max(0.0, float(point[0]) / max(width, 1)))
            y = min(1.0, max(0.0, float(point[1]) / max(height, 1)))
            points.append((x, y))
        return tuple(points)

    @classmethod
    def _regions_from_payload(
        cls,
        payload: dict[str, Any],
        width: int,
        height: int,
    ) -> tuple[OCRTextRegion, ...]:
        def as_list(value: Any) -> list[Any]:
            if value is None:
                return []
            if hasattr(value, "tolist"):
                value = value.tolist()
            return list(value)

        texts = as_list(payload.get("rec_texts"))
        scores = as_list(payload.get("rec_scores"))
        polygons = as_list(payload.get("rec_polys"))

        regions: list[OCRTextRegion] = []
        for index, text in enumerate(texts):
            clean_text = str(text).strip()
            if not clean_text:
                continue
            score = float(scores[index]) if index < len(scores) else 0.0
            polygon = polygons[index] if index < len(polygons) else []
            regions.append(
                OCRTextRegion(
                    id=f"r{index + 1}",
                    text=clean_text,
                    confidence=max(0.0, min(1.0, score)),
                    polygon=cls._normalise_polygon(polygon, width, height),
                )
            )
        return tuple(regions)

    def extract(self, raw: bytes) -> OCRResult:
        try:
            image = load_oriented_rgb_image(raw)
        except Exception as exc:
            raise RuntimeError("The uploaded file is not a readable image.") from exc

        width, height = image.size
        if width < 80 or height < 80:
            raise RuntimeError(
                "Image is too small for reliable OCR; use a larger label image."
            )

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            temp_path = Path(tmp.name)

        try:
            image.save(temp_path, format="PNG")
            pipeline = self._get_pipeline()
            with warnings.catch_warnings():
                warnings.simplefilter("error", DeprecationWarning)
                warnings.simplefilter("error", FutureWarning)
                prediction = pipeline.predict(str(temp_path))
                regions: list[OCRTextRegion] = []
                for page_result in prediction:
                    payload = self._coerce_payload(page_result)
                    regions.extend(
                        self._regions_from_payload(payload, width, height)
                    )
        finally:
            temp_path.unlink(missing_ok=True)

        text = "\n".join(region.text for region in regions).strip()
        return OCRResult(
            text=text,
            engine=self.name,
            width=width,
            height=height,
            regions=tuple(regions),
        )


    def recognize_text_line(self, raw: bytes) -> OCRResult:
        """Recognize one already-localized text-line image without detection.

        The result uses a full-image polygon because the recognition module is
        intentionally told that the complete input image is the text candidate.
        Geometry is later mapped back through the ImageVariant source rectangle.
        """

        try:
            image = load_oriented_rgb_image(raw)
        except Exception as exc:
            raise RuntimeError("The targeted OCR input is not a readable image.") from exc

        width, height = image.size
        if width < 8 or height < 8:
            return OCRResult(
                text="",
                engine=f"{self.name} / direct text recognition",
                width=width,
                height=height,
            )

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            temp_path = Path(tmp.name)

        try:
            image.save(temp_path, format="PNG")
            recognizer = self._get_text_recognizer()
            with warnings.catch_warnings():
                warnings.simplefilter("error", DeprecationWarning)
                warnings.simplefilter("error", FutureWarning)
                prediction = recognizer.predict(input=str(temp_path), batch_size=1)
                regions: list[OCRTextRegion] = []
                for index, recognition_result in enumerate(prediction, start=1):
                    payload = self._coerce_payload(recognition_result)
                    text = str(payload.get("rec_text") or "").strip()
                    if not text:
                        continue
                    try:
                        score = float(payload.get("rec_score") or 0.0)
                    except (TypeError, ValueError):
                        score = 0.0
                    regions.append(
                        OCRTextRegion(
                            id=f"dr{index}",
                            text=text,
                            confidence=max(0.0, min(1.0, score)),
                            polygon=((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)),
                            source="direct-recognition",
                        )
                    )
        finally:
            temp_path.unlink(missing_ok=True)

        text = "\n".join(region.text for region in regions).strip()
        return OCRResult(
            text=text,
            engine=f"{self.name} / direct text recognition",
            width=width,
            height=height,
            regions=tuple(regions),
        )


_ENGINE: PaddleOcrOnnxEngine | None = None
_ENGINE_LOCK = threading.Lock()


def get_ocr_engine() -> PaddleOcrOnnxEngine:
    global _ENGINE
    if _ENGINE is None:
        with _ENGINE_LOCK:
            if _ENGINE is None:
                _ENGINE = PaddleOcrOnnxEngine()
    return _ENGINE
