from dataclasses import dataclass
from math import hypot

import numpy as np
from PIL import Image


@dataclass(frozen=True)
class DetectedBox:
    points: tuple[tuple[float, float], ...]
    score: float

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        xs = [point[0] for point in self.points]
        ys = [point[1] for point in self.points]
        return min(xs), min(ys), max(xs), max(ys)


def _ordered_points(box: DetectedBox) -> tuple[tuple[float, float], ...]:
    points = np.asarray(box.points, dtype=np.float32)
    sums = points.sum(axis=1)
    differences = np.diff(points, axis=1).ravel()
    return (
        tuple(points[np.argmin(sums)]),
        tuple(points[np.argmin(differences)]),
        tuple(points[np.argmax(sums)]),
        tuple(points[np.argmax(differences)]),
    )


def warp_box(image: Image.Image, box: DetectedBox) -> Image.Image:
    top_left, top_right, bottom_right, bottom_left = _ordered_points(box)
    width = max(
        1,
        round(
            max(
                hypot(top_right[0] - top_left[0], top_right[1] - top_left[1]),
                hypot(bottom_right[0] - bottom_left[0], bottom_right[1] - bottom_left[1]),
            )
        ),
    )
    height = max(
        1,
        round(
            max(
                hypot(bottom_left[0] - top_left[0], bottom_left[1] - top_left[1]),
                hypot(bottom_right[0] - top_right[0], bottom_right[1] - top_right[1]),
            )
        ),
    )
    quad = (*top_left, *bottom_left, *bottom_right, *top_right)
    result = image.convert("RGB").transform(
        (width, height),
        Image.Transform.QUAD,
        quad,
        resample=Image.Resampling.BICUBIC,
    )
    if result.height > result.width * 1.8:
        result = result.rotate(90, expand=True)
    return result


def _same_row(first: DetectedBox, second: DetectedBox) -> bool:
    _, top_a, _, bottom_a = first.bounds
    _, top_b, _, bottom_b = second.bounds
    height_a = max(1.0, bottom_a - top_a)
    height_b = max(1.0, bottom_b - top_b)
    overlap = max(0.0, min(bottom_a, bottom_b) - max(top_a, top_b))
    center_distance = abs((top_a + bottom_a) / 2 - (top_b + bottom_b) / 2)
    return overlap >= min(height_a, height_b) * 0.5 or center_distance <= max(height_a, height_b) * 0.5


def sort_reading_order(boxes: list[DetectedBox]) -> list[DetectedBox]:
    rows: list[list[DetectedBox]] = []
    for box in sorted(boxes, key=lambda item: (item.bounds[1] + item.bounds[3]) / 2):
        for row in rows:
            if _same_row(row[0], box):
                row.append(box)
                break
        else:
            rows.append([box])
    rows.sort(key=lambda row: np.median([(item.bounds[1] + item.bounds[3]) / 2 for item in row]))
    ordered: list[DetectedBox] = []
    for row in rows:
        ordered.extend(sorted(row, key=lambda item: (item.bounds[0] + item.bounds[2]) / 2))
    return ordered

