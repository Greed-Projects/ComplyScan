from __future__ import annotations

import io

from PIL import Image, ImageOps


def load_oriented_rgb_image(raw: bytes) -> Image.Image:
    """Decode an uploaded image into the canonical visual orientation.

    Phone cameras commonly store landscape photos as portrait pixel data plus
    an EXIF Orientation tag. Browsers honor that tag automatically, while plain
    ``PIL.Image.open(...).convert('RGB')`` does not. PackCheck must normalize
    orientation before *both* OCR and computer-vision processing so region
    geometry, previews, and OCR evidence refer to the same visual image.
    """

    with Image.open(io.BytesIO(raw)) as image:
        oriented = ImageOps.exif_transpose(image)
        return oriented.convert("RGB").copy()
