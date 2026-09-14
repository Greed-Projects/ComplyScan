from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Iterable

import cv2
import numpy as np
from PIL import Image

from .image_io import load_oriented_rgb_image


@dataclass(frozen=True, slots=True)
class CropCandidate:
    label: str
    x: int
    y: int
    width: int
    height: int
    score: float


@dataclass(frozen=True, slots=True)
class ImageVariant:
    """One OCR representation plus its geometry in the original image.

    Transformations may resize, invert, threshold, or enhance pixels, but the
    ``source_*`` rectangle always describes the untransformed original-image
    area represented by this variant. That allows OCR polygons to be mapped
    back to the package photograph without guessing.
    """

    name: str
    family: str
    raw: bytes
    source_x: int
    source_y: int
    source_width: int
    source_height: int


class InvalidImageError(RuntimeError):
    pass


def image_from_bytes(raw: bytes) -> np.ndarray:
    try:
        rgb = np.asarray(load_oriented_rgb_image(raw))
    except Exception as exc:
        raise InvalidImageError("The uploaded file is not a readable image.") from exc
    return rgb


def _candidate_iou(a: CropCandidate, b: CropCandidate) -> float:
    left = max(a.x, b.x)
    top = max(a.y, b.y)
    right = min(a.x + a.width, b.x + b.width)
    bottom = min(a.y + a.height, b.y + b.height)
    if right <= left or bottom <= top:
        return 0.0
    intersection = (right - left) * (bottom - top)
    union = a.width * a.height + b.width * b.height - intersection
    return intersection / max(union, 1)


def _dedupe_candidates(
    candidates: Iterable[CropCandidate],
    limit: int = 3,
) -> tuple[CropCandidate, ...]:
    selected: list[CropCandidate] = []
    for candidate in sorted(candidates, key=lambda item: item.score, reverse=True):
        if any(_candidate_iou(candidate, current) >= 0.60 for current in selected):
            continue
        selected.append(candidate)
        if len(selected) >= limit:
            break
    return tuple(selected)


def _projection_seal_candidates(
    gray: np.ndarray,
    image_width: int,
    image_height: int,
) -> list[CropCandidate]:
    """Find long dark horizontal bands using row/column occupancy.

    Contour-based dark-band detection works well when the seal is cleanly
    separated from the rest of the package. Hand-held photographs can connect
    the seal to a hand, shadow, or printed panel in the binary mask, causing
    the resulting contour to become too tall and get rejected. Row projection
    is deliberately insensitive to that connectivity: it asks whether a broad
    horizontal run of rows is predominantly dark, then estimates the useful
    horizontal span inside that run.
    """

    if image_height < 32 or image_width < 64:
        return []

    top = int(image_height * 0.08)
    bottom = int(image_height * 0.84)
    left = int(image_width * 0.03)
    right = max(left + 1, int(image_width * 0.97))
    central = gray[top:bottom, left:right]
    if central.size == 0:
        return []

    candidates: list[CropCandidate] = []
    min_run = max(8, int(round(image_height * 0.012)))

    for threshold in (90, 110, 130):
        row_coverage = np.mean(central < threshold, axis=1)
        active = (row_coverage >= 0.55).astype(np.uint8) * 255

        # Close short vertical gaps introduced by reflections, folds, or the
        # dot-matrix characters themselves.
        gap = max(5, int(round(image_height * 0.010)))
        if gap % 2 == 0:
            gap += 1
        closed = cv2.morphologyEx(
            active.reshape(-1, 1),
            cv2.MORPH_CLOSE,
            np.ones((gap, 1), dtype=np.uint8),
        ).reshape(-1)

        run_start: int | None = None
        for index in range(len(closed) + 1):
            on = index < len(closed) and closed[index] > 0
            if on and run_start is None:
                run_start = index
                continue
            if on or run_start is None:
                continue

            run_end = index
            run_height = run_end - run_start
            if run_height < min_run:
                run_start = None
                continue

            y = top + run_start
            h = run_height
            height_ratio = h / max(image_height, 1)
            if not 0.012 <= height_ratio <= 0.22:
                run_start = None
                continue

            band = gray[y : y + h]
            column_coverage = np.mean(band < threshold, axis=0)
            horizontal = (column_coverage >= 0.35).astype(np.uint8) * 255

            # Bridge small horizontal gaps so a reflection or wrinkle does not
            # split one long seal into several fragments.
            bridge = max(15, int(round(image_width * 0.02)))
            bridged = cv2.morphologyEx(
                horizontal.reshape(1, -1),
                cv2.MORPH_CLOSE,
                np.ones((1, bridge), dtype=np.uint8),
            ).reshape(-1)

            best_start = 0
            best_end = 0
            segment_start: int | None = None
            for column in range(len(bridged) + 1):
                enabled = column < len(bridged) and bridged[column] > 0
                if enabled and segment_start is None:
                    segment_start = column
                    continue
                if enabled or segment_start is None:
                    continue
                if column - segment_start > best_end - best_start:
                    best_start, best_end = segment_start, column
                segment_start = None

            width = best_end - best_start
            width_ratio = width / max(image_width, 1)
            if width_ratio < 0.38:
                run_start = None
                continue

            mean_coverage = float(np.mean(row_coverage[run_start:run_end]))
            center_y = (y + h / 2) / max(image_height, 1)
            centre_preference = max(0.30, 1.0 - abs(center_y - 0.45))
            aspect = width / max(h, 1)
            score = (
                width_ratio
                * min(aspect / 10.0, 2.0)
                * max(mean_coverage, 0.05)
                * centre_preference
            )

            margin_x = int(image_width * 0.012)
            margin_y = max(3, int(image_height * 0.010))
            x0 = max(0, best_start - margin_x)
            y0 = max(0, y - margin_y)
            x1 = min(image_width, best_end + margin_x)
            y1 = min(image_height, y + h + margin_y)
            candidates.append(
                CropCandidate(
                    label=f"seal-row-{threshold}",
                    x=x0,
                    y=y0,
                    width=max(1, x1 - x0),
                    height=max(1, y1 - y0),
                    score=score,
                )
            )
            run_start = None

    return candidates


def find_target_crops(raw: bytes, locator: str) -> tuple[CropCandidate, ...]:
    """Locate package regions referenced by declarations such as "under seal".

    Seal recovery favours long horizontal dark bands. The detector is purely
    visual: it does not know the expected MRP, currency, or legal result.
    """

    rgb = image_from_bytes(raw)
    height, width = rgb.shape[:2]

    if locator == "bottom":
        y = int(height * 0.62)
        return (CropCandidate("bottom-zone", 0, y, width, height - y, 1.0),)
    if locator == "top":
        h = max(1, int(height * 0.40))
        return (CropCandidate("top-zone", 0, 0, width, h, 1.0),)

    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    candidates: list[CropCandidate] = _projection_seal_candidates(
        gray,
        width,
        height,
    )

    for threshold in (70, 90, 110):
        mask = np.zeros_like(gray, dtype=np.uint8)
        central_top = int(height * 0.08)
        central_bottom = int(height * 0.84)
        mask[central_top:central_bottom] = (
            gray[central_top:central_bottom] < threshold
        ).astype(np.uint8) * 255

        kernel_width = max(31, int(width * 0.05))
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_width, 5))
        joined = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)
        contours, _ = cv2.findContours(
            joined,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )

        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            width_ratio = w / max(width, 1)
            height_ratio = h / max(height, 1)
            aspect = w / max(h, 1)
            if width_ratio < 0.38 or not 0.018 <= height_ratio <= 0.22 or aspect < 4.0:
                continue

            patch = gray[y : y + h, x : x + w]
            if patch.size == 0:
                continue
            dark_fraction = float(np.mean(patch < threshold))
            center_y = (y + h / 2) / max(height, 1)
            centre_preference = max(0.25, 1.0 - abs(center_y - 0.45))

            # A small horizontal-edge term helps prefer a dark band containing
            # printed glyphs over a featureless shadow/furniture edge.
            sobel_x = cv2.Sobel(patch, cv2.CV_32F, 1, 0, ksize=3)
            edge_energy = float(np.mean(np.abs(sobel_x))) / 255.0
            score = (
                width_ratio
                * min(aspect / 10.0, 2.0)
                * max(dark_fraction, 0.05)
                * centre_preference
                * (1.0 + min(edge_energy, 0.7))
            )

            margin_x = int(width * 0.015)
            margin_y = int(height * 0.018)
            cx = max(0, x - margin_x)
            cy = max(0, y - margin_y)
            cr = min(width, x + w + margin_x)
            cb = min(height, y + h + margin_y)
            candidates.append(
                CropCandidate(
                    label=f"seal-dark-{threshold}",
                    x=cx,
                    y=cy,
                    width=max(1, cr - cx),
                    height=max(1, cb - cy),
                    score=score,
                )
            )

    if not candidates:
        y = int(height * 0.22)
        h = max(1, int(height * 0.45))
        candidates.append(
            CropCandidate(
                "seal-middle-fallback",
                0,
                y,
                width,
                min(h, height - y),
                0.2,
            )
        )

    return _dedupe_candidates(candidates)


def _encode_png(image: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    Image.fromarray(image).save(buffer, format="PNG")
    return buffer.getvalue()


def _resize_for_ocr(image: np.ndarray, target_height: int) -> np.ndarray:
    height, width = image.shape[:2]
    if height <= 0 or width <= 0:
        return image
    scale = max(1.0, min(5.0, target_height / height))
    new_width = max(1, min(4200, int(round(width * scale))))
    new_height = max(1, int(round(height * (new_width / width))))
    interpolation = cv2.INTER_CUBIC if new_height >= height else cv2.INTER_AREA
    return cv2.resize(image, (new_width, new_height), interpolation=interpolation)


def _strongest_text_band(
    patch: np.ndarray,
) -> tuple[int, int, int, int]:
    """Return a likely horizontal text-line band inside a target crop.

    The score combines local gradients with a darkness preference. This is
    particularly useful for faint dot-matrix printing on a glossy black seal:
    the characters may be too weak for a text detector in the full crop, but
    their small edge structures form a clear horizontal energy band.
    """

    height, width = patch.shape[:2]
    if height < 32 or width < 64:
        return 0, 0, width, height

    gray = cv2.cvtColor(patch, cv2.COLOR_RGB2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(8, 8)).apply(gray)
    grad_x = cv2.Sobel(clahe, cv2.CV_32F, 1, 0, ksize=3)
    grad_y = cv2.Sobel(clahe, cv2.CV_32F, 0, 1, ksize=3)
    magnitude = cv2.magnitude(grad_x, grad_y)

    # Dark-film preference is soft rather than binary so bright reflections do
    # not completely suppress text near them.
    dark_weight = np.clip((175.0 - gray.astype(np.float32)) / 120.0, 0.15, 1.0)
    row_score = np.mean(magnitude * dark_weight, axis=1)

    smoothing = max(7, int(round(height * 0.09)))
    if smoothing % 2 == 0:
        smoothing += 1
    kernel = np.ones(smoothing, dtype=np.float32) / smoothing
    smooth = np.convolve(row_score, kernel, mode="same")

    search_top = max(0, int(height * 0.08))
    search_bottom = min(height, max(search_top + 1, int(height * 0.92)))
    peak = search_top + int(np.argmax(smooth[search_top:search_bottom]))

    band_height = int(round(height * 0.46))
    band_height = max(46, min(band_height, 140, height))
    y0 = max(0, peak - int(round(band_height * 0.52)))
    y1 = min(height, y0 + band_height)
    if y1 - y0 < band_height:
        y0 = max(0, y1 - band_height)

    x_margin = min(int(width * 0.015), 24)
    x0 = max(0, x_margin)
    x1 = max(x0 + 1, width - x_margin)
    return x0, y0, x1 - x0, y1 - y0


def _gamma_lut(gamma: float) -> np.ndarray:
    return np.array(
        [min(255, int(round(((value / 255.0) ** gamma) * 255.0))) for value in range(256)],
        dtype=np.uint8,
    )


def _variant(
    *,
    name: str,
    family: str,
    image: np.ndarray,
    source_x: int,
    source_y: int,
    source_width: int,
    source_height: int,
) -> ImageVariant:
    return ImageVariant(
        name=name,
        family=family,
        raw=_encode_png(image),
        source_x=source_x,
        source_y=source_y,
        source_width=source_width,
        source_height=source_height,
    )


def preprocessing_variants(raw: bytes, crop: CropCandidate) -> tuple[ImageVariant, ...]:
    """Build a bounded multi-view OCR ensemble for one target region.

    Inversion is intentionally one *member* of the ensemble, not a global
    replacement. Different print/background combinations benefit from different
    representations, and the fusion layer can compare the OCR evidence.
    """

    rgb = image_from_bytes(raw)
    patch = rgb[crop.y : crop.y + crop.height, crop.x : crop.x + crop.width]
    if patch.size == 0:
        return tuple()

    # Keep two conservative full-region views in case the text-band detector is
    # imperfect. The remaining variants focus on the strongest line band.
    full_color = _resize_for_ocr(patch, target_height=300)
    full_gray_source = cv2.cvtColor(patch, cv2.COLOR_RGB2GRAY)
    full_clahe = cv2.createCLAHE(clipLimit=2.4, tileGridSize=(8, 8)).apply(
        full_gray_source
    )
    full_clahe = _resize_for_ocr(full_clahe, target_height=300)

    bx, by, bw, bh = _strongest_text_band(patch)
    line = patch[by : by + bh, bx : bx + bw]
    line_gray = cv2.cvtColor(line, cv2.COLOR_RGB2GRAY)
    line_clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 4)).apply(line_gray)
    line_gamma = cv2.LUT(line_clahe, _gamma_lut(0.58))

    # Bright small dot-matrix structures on dark film are enhanced by white
    # top-hat. Kernel sizes are intentionally small compared with character
    # height so the printed dots survive while slow illumination changes fade.
    morphology_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (13, 5))
    top_hat = cv2.morphologyEx(line_clahe, cv2.MORPH_TOPHAT, morphology_kernel)
    top_hat = cv2.normalize(top_hat, None, 0, 255, cv2.NORM_MINMAX)

    adaptive = cv2.adaptiveThreshold(
        line_clahe,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        -3,
    )

    line_color_up = _resize_for_ocr(line, target_height=190)
    line_clahe_up = _resize_for_ocr(line_clahe, target_height=190)
    line_gamma_up = _resize_for_ocr(line_gamma, target_height=190)
    top_hat_up = _resize_for_ocr(top_hat, target_height=190)
    adaptive_up = _resize_for_ocr(adaptive, target_height=190)

    source_x = crop.x + bx
    source_y = crop.y + by

    return (
        _variant(
            name="full-original",
            family="baseline",
            image=full_color,
            source_x=crop.x,
            source_y=crop.y,
            source_width=crop.width,
            source_height=crop.height,
        ),
        _variant(
            name="full-clahe",
            family="local-contrast",
            image=full_clahe,
            source_x=crop.x,
            source_y=crop.y,
            source_width=crop.width,
            source_height=crop.height,
        ),
        _variant(
            name="line-original",
            family="line-localization",
            image=line_color_up,
            source_x=source_x,
            source_y=source_y,
            source_width=bw,
            source_height=bh,
        ),
        _variant(
            name="line-clahe",
            family="local-contrast",
            image=line_clahe_up,
            source_x=source_x,
            source_y=source_y,
            source_width=bw,
            source_height=bh,
        ),
        _variant(
            name="line-clahe-inverted",
            family="polarity",
            image=cv2.bitwise_not(line_clahe_up),
            source_x=source_x,
            source_y=source_y,
            source_width=bw,
            source_height=bh,
        ),
        _variant(
            name="line-gamma",
            family="illumination",
            image=line_gamma_up,
            source_x=source_x,
            source_y=source_y,
            source_width=bw,
            source_height=bh,
        ),
        _variant(
            name="line-gamma-inverted",
            family="polarity",
            image=cv2.bitwise_not(line_gamma_up),
            source_x=source_x,
            source_y=source_y,
            source_width=bw,
            source_height=bh,
        ),
        _variant(
            name="line-tophat",
            family="morphology",
            image=top_hat_up,
            source_x=source_x,
            source_y=source_y,
            source_width=bw,
            source_height=bh,
        ),
        _variant(
            name="line-tophat-inverted",
            family="morphology-polarity",
            image=cv2.bitwise_not(top_hat_up),
            source_x=source_x,
            source_y=source_y,
            source_width=bw,
            source_height=bh,
        ),
        _variant(
            name="line-adaptive",
            family="threshold",
            image=adaptive_up,
            source_x=source_x,
            source_y=source_y,
            source_width=bw,
            source_height=bh,
        ),
    )

def attention_tile_variants(raw: bytes, crop: CropCandidate) -> tuple[ImageVariant, ...]:
    """Build overlapping horizontal attention windows over the strongest text band.

    Wide seal lines are hostile to OCR because the recognizer/detector must
    process a very large aspect ratio at once. Human readers naturally zoom
    into a smaller part of the strip. These tiles mimic that spatial-attention
    step while preserving overlap so a price near a tile boundary is not lost.

    This is intentionally a second-stage fallback. The normal bounded ensemble
    should run first; callers should invoke these tiles only when the wide views
    fail to produce a reliable declaration candidate.
    """

    rgb = image_from_bytes(raw)
    patch = rgb[crop.y : crop.y + crop.height, crop.x : crop.x + crop.width]
    if patch.size == 0:
        return tuple()

    bx, by, bw, bh = _strongest_text_band(patch)
    if bw < 420 or bh <= 0:
        return tuple()

    line = patch[by : by + bh, bx : bx + bw]
    line_gray = cv2.cvtColor(line, cv2.COLOR_RGB2GRAY)
    line_clahe = cv2.createCLAHE(clipLimit=3.2, tileGridSize=(8, 4)).apply(line_gray)
    line_gamma = cv2.LUT(line_clahe, _gamma_lut(0.62))

    # Keep each OCR view narrow enough that dot-matrix characters retain useful
    # pixel height after OCR's internal resizing. Roughly one third of the line
    # with 45% overlap gives four-to-five views on a typical package seal.
    tile_width = max(320, min(680, int(round(bw * 0.36))))
    tile_width = min(tile_width, bw)
    step = max(160, int(round(tile_width * 0.55)))

    starts = list(range(0, max(1, bw - tile_width + 1), step))
    final_start = max(0, bw - tile_width)
    if not starts or starts[-1] != final_start:
        starts.append(final_start)

    # Bound runtime. Preserve coverage by sampling evenly if an unusually wide
    # crop would otherwise create more than five windows.
    if len(starts) > 5:
        indices = np.linspace(0, len(starts) - 1, 5).round().astype(int)
        starts = [starts[index] for index in indices]

    unique_starts: list[int] = []
    for start in starts:
        if start not in unique_starts:
            unique_starts.append(start)

    variants: list[ImageVariant] = []
    source_y = crop.y + by
    for index, start in enumerate(unique_starts, start=1):
        end = min(bw, start + tile_width)
        actual_width = end - start
        if actual_width <= 0:
            continue

        clahe_tile = line_clahe[:, start:end]
        gamma_tile = line_gamma[:, start:end]
        clahe_up = _resize_for_ocr(clahe_tile, target_height=220)
        gamma_up = _resize_for_ocr(gamma_tile, target_height=220)
        source_x = crop.x + bx + start

        variants.append(
            _variant(
                name=f"attention-{index:02d}-clahe",
                family="attention-local-contrast",
                image=clahe_up,
                source_x=source_x,
                source_y=source_y,
                source_width=actual_width,
                source_height=bh,
            )
        )
        variants.append(
            _variant(
                name=f"attention-{index:02d}-gamma-inverted",
                family="attention-polarity",
                image=cv2.bitwise_not(gamma_up),
                source_x=source_x,
                source_y=source_y,
                source_width=actual_width,
                source_height=bh,
            )
        )

    return tuple(variants)

