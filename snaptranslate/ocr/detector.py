from math import ceil

import numpy as np
import onnxruntime as ort
from PIL import Image

from ..resource_path import model_path
from .geometry import DetectedBox
from .recognizer import OcrModelError


def _component_points(active: np.ndarray) -> list[np.ndarray]:
    height, width = active.shape
    visited = np.zeros_like(active, dtype=bool)
    components: list[np.ndarray] = []
    for y, x in zip(*np.where(active), strict=True):
        if visited[y, x]:
            continue
        visited[y, x] = True
        pending = [(int(y), int(x))]
        points: list[tuple[int, int]] = []
        while pending:
            current_y, current_x = pending.pop()
            points.append((current_x, current_y))
            for next_y in range(max(0, current_y - 1), min(height, current_y + 2)):
                for next_x in range(max(0, current_x - 1), min(width, current_x + 2)):
                    if active[next_y, next_x] and not visited[next_y, next_x]:
                        visited[next_y, next_x] = True
                        pending.append((next_y, next_x))
        components.append(np.asarray(points, dtype=np.float32))
    return components


def boxes_from_probability_map(
    probability: np.ndarray,
    threshold: float = 0.3,
    box_threshold: float = 0.6,
    scale_x: float = 1.0,
    scale_y: float = 1.0,
) -> list[DetectedBox]:
    probability = np.asarray(probability, dtype=np.float32)
    boxes: list[DetectedBox] = []
    for points in _component_points(probability >= threshold):
        if len(points) < 10 or np.ptp(points[:, 0]) < 2 or np.ptp(points[:, 1]) < 2:
            continue
        indices = points.astype(np.int32)
        score = float(probability[indices[:, 1], indices[:, 0]].mean())
        if score < box_threshold:
            continue
        center = points.mean(axis=0)
        covariance = np.cov((points - center).T)
        eigenvalues, eigenvectors = np.linalg.eigh(covariance)
        axes = eigenvectors[:, np.argsort(eigenvalues)[::-1]]
        projected = (points - center) @ axes
        minimum = projected.min(axis=0)
        maximum = projected.max(axis=0)
        span = maximum - minimum
        # DB probability maps follow the dense center strokes and can omit glyph
        # ascenders/descenders. Keep the long text axis tight, but use the
        # PaddleOCR-style generous margin perpendicular to the text line.
        expansion = np.maximum(span * np.array((0.12, 0.43)), 1.0)
        minimum -= expansion
        maximum += expansion
        local_corners = np.array(
            [
                [minimum[0], minimum[1]],
                [maximum[0], minimum[1]],
                [maximum[0], maximum[1]],
                [minimum[0], maximum[1]],
            ],
            dtype=np.float32,
        )
        corners = local_corners @ axes.T + center
        scaled = tuple((float(x * scale_x), float(y * scale_y)) for x, y in corners)
        boxes.append(DetectedBox(scaled, score))
    return boxes


class OnnxDetector:
    def __init__(self, session) -> None:
        self.session = session
        self.input_name = session.get_inputs()[0].name

    def detect(self, image: Image.Image) -> list[DetectedBox]:
        rgb = image.convert("RGB")
        reduction = min(1.0, 960 / max(rgb.width, rgb.height))
        target_width = max(32, ceil(rgb.width * reduction / 32) * 32)
        target_height = max(32, ceil(rgb.height * reduction / 32) * 32)
        resized = rgb.resize((target_width, target_height), Image.Resampling.BILINEAR)
        tensor = np.asarray(resized, dtype=np.float32) / 255.0
        tensor = (tensor - np.array((0.485, 0.456, 0.406), dtype=np.float32)) / np.array(
            (0.229, 0.224, 0.225), dtype=np.float32
        )
        tensor = np.transpose(tensor, (2, 0, 1))[None, ...].astype(np.float32, copy=False)
        outputs = self.session.run(None, {self.input_name: tensor})
        if not outputs:
            raise OcrModelError("检测模型没有返回输出")
        probability = np.squeeze(np.asarray(outputs[0], dtype=np.float32))
        if probability.ndim != 2:
            raise OcrModelError(f"无法识别的检测输出形状：{np.asarray(outputs[0]).shape}")
        return boxes_from_probability_map(
            probability,
            scale_x=rgb.width / probability.shape[1],
            scale_y=rgb.height / probability.shape[0],
        )


def load_default_detector() -> OnnxDetector:
    path = model_path("PP-OCRv5_mobile_det.onnx")
    if not path.is_file():
        raise OcrModelError("OCR 检测模型缺失")
    return OnnxDetector(ort.InferenceSession(str(path), providers=["CPUExecutionProvider"]))
