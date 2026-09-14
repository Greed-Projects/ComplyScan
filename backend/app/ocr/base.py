from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True, slots=True)
class OCRTextRegion:
    id: str
    text: str
    confidence: float
    # Normalized coordinates in the range [0, 1], starting at the image top-left.
    polygon: tuple[tuple[float, float], ...]
    # "primary" for the full-image OCR pass. Targeted recovery uses a descriptive
    # source string so downstream/UI diagnostics can preserve provenance.
    source: str = "primary"

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        if not self.polygon:
            return (0.0, 0.0, 0.0, 0.0)
        xs = [point[0] for point in self.polygon]
        ys = [point[1] for point in self.polygon]
        left, top = min(xs), min(ys)
        right, bottom = max(xs), max(ys)
        return (left, top, right - left, bottom - top)


@dataclass(frozen=True, slots=True)
class OCRResult:
    text: str
    engine: str
    width: int
    height: int
    regions: tuple[OCRTextRegion, ...] = field(default_factory=tuple)


class OcrEngine(Protocol):
    @property
    def name(self) -> str: ...

    def extract(self, raw: bytes) -> OCRResult: ...


class TextLineRecognizer(Protocol):
    """Optional OCR capability for an already-localized text-line image.

    End-to-end OCR engines normally perform both text detection and recognition.
    Targeted recovery can bypass detection once computer vision has already
    isolated a narrow text line or attention tile.
    """

    def recognize_text_line(self, raw: bytes) -> OCRResult: ...
