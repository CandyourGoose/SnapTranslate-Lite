import numpy as np
from PIL import Image, ImageOps

from .types import LineCandidate


def _gray(image: Image.Image) -> np.ndarray:
    return np.asarray(image.convert("L"), dtype=np.float32)


def _border_level(gray: np.ndarray) -> float:
    if gray.shape[0] < 4 or gray.shape[1] < 4:
        return float(np.median(gray))
    border = np.concatenate(
        (gray[:2, :].ravel(), gray[-2:, :].ravel(), gray[:, :2].ravel(), gray[:, -2:].ravel())
    )
    return float(np.median(border))


def trim_background(image: Image.Image) -> Image.Image:
    rgb = image.convert("RGB")
    gray = _gray(rgb)
    active_y, active_x = np.where(np.abs(gray - _border_level(gray)) > 18)
    if active_x.size < 12:
        return rgb
    left = max(0, int(active_x.min()) - 4)
    top = max(0, int(active_y.min()) - 4)
    right = min(rgb.width, int(active_x.max()) + 5)
    bottom = min(rgb.height, int(active_y.max()) + 5)
    return rgb.crop((left, top, right, bottom))


def _active_bands(rows: np.ndarray) -> list[tuple[int, int]]:
    active = rows.astype(bool).copy()
    false_positions = np.flatnonzero(~active)
    for start in false_positions:
        if active[start]:
            continue
        end = start
        while end + 1 < len(active) and not active[end + 1]:
            end += 1
        if start > 0 and end + 1 < len(active) and end - start + 1 <= 2:
            active[start : end + 1] = True
    indices = np.flatnonzero(active)
    if not indices.size:
        return []
    bands: list[tuple[int, int]] = []
    start = previous = int(indices[0])
    for value in indices[1:]:
        value = int(value)
        if value > previous + 1:
            bands.append((start, previous + 1))
            start = value
        previous = value
    bands.append((start, previous + 1))
    return bands


def likely_single_line(image: Image.Image) -> bool:
    gray = _gray(image)
    active = np.abs(gray - _border_level(gray)) > 18
    row_counts = active.sum(axis=1)
    bands = _active_bands(row_counts >= max(2, gray.shape[1] * 0.01))
    return len(bands) == 1 and bands[0][1] - bands[0][0] >= 4


def recognition_variants(image: Image.Image) -> list[LineCandidate]:
    original = trim_background(image)
    candidates = [LineCandidate(original, 1.0)]
    if original.height < 40:
        candidates.append(
            LineCandidate(
                original.resize((original.width * 2, original.height * 2), Image.Resampling.LANCZOS),
                2.0,
            )
        )

    gray = _gray(original)
    contrast = float(gray.max() - gray.min()) if gray.size else 0.0
    if contrast < 45:
        candidates.append(LineCandidate(ImageOps.autocontrast(original, cutoff=1).convert("RGB"), 1.0))

    unique: list[LineCandidate] = []
    seen: set[tuple[tuple[int, int], bytes]] = set()
    for candidate in candidates:
        key = (candidate.image.size, candidate.image.tobytes())
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
        if len(unique) == 3:
            break
    return unique
