"""Computer-vision helpers used before OCR.

The vision layer is deliberately independent of Legal Metrology rules. It only
locates likely package regions and produces OCR-friendly image representations.
"""

from .preprocessing import CropCandidate, ImageVariant, find_target_crops, preprocessing_variants

__all__ = [
    "CropCandidate",
    "ImageVariant",
    "find_target_crops",
    "preprocessing_variants",
]
