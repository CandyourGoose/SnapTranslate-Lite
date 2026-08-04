from math import ceil
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image

from ..resource_path import model_path
from .types import RecognizedLine


class OcrModelError(RuntimeError):
    pass


class CtcDecoder:
    def __init__(self, labels: list[str]) -> None:
        self.labels = tuple(labels)

    def decode(self, logits: np.ndarray) -> RecognizedLine:
        values = np.asarray(logits, dtype=np.float32)
        if values.ndim != 3 or values.shape[0] != 1:
            raise OcrModelError(f"无法识别的 CTC 输出形状：{values.shape}")
        expected_classes = len(self.labels) + 1
        if values.shape[-1] != expected_classes:
            raise OcrModelError(
                f"模型类别数 {values.shape[-1]} 与字典类别数 {expected_classes} 不一致"
            )

        row_sums = values.sum(axis=-1)
        if np.all(values >= 0) and np.allclose(row_sums, 1.0, atol=1e-3):
            probabilities = values
        else:
            shifted = values - values.max(axis=-1, keepdims=True)
            exponentials = np.exp(shifted)
            probabilities = exponentials / exponentials.sum(axis=-1, keepdims=True)

        indices = probabilities.argmax(axis=-1)[0]
        confidences = probabilities.max(axis=-1)[0]
        characters: list[str] = []
        retained: list[float] = []
        previous = -1
        for index, confidence in zip(indices, confidences, strict=True):
            current = int(index)
            if current != 0 and current != previous:
                characters.append(self.labels[current - 1])
                retained.append(float(confidence))
            previous = current
        if not characters:
            return RecognizedLine("", 0.0)
        return RecognizedLine("".join(characters), float(np.mean(retained)))


class OnnxRecognizer:
    def __init__(self, session, decoder: CtcDecoder) -> None:
        self.session = session
        self.decoder = decoder
        model_input = session.get_inputs()[0]
        self.input_name = model_input.name
        self.input_shape = model_input.shape

    @staticmethod
    def _tensor(image: Image.Image) -> np.ndarray:
        rgb = image.convert("RGB")
        scaled_width = max(1, round(rgb.width * 48 / max(1, rgb.height)))
        padded_width = min(960, max(32, ceil(scaled_width / 32) * 32))
        resized_width = min(scaled_width, padded_width)
        resized = rgb.resize((resized_width, 48), Image.Resampling.BICUBIC)
        canvas = Image.new("RGB", (padded_width, 48), "white")
        canvas.paste(resized, (0, 0))
        array = np.asarray(canvas, dtype=np.float32) / 255.0
        array = (array - 0.5) / 0.5
        return np.transpose(array, (2, 0, 1))[None, ...].astype(np.float32, copy=False)

    def recognize(self, image: Image.Image) -> RecognizedLine:
        tensor = self._tensor(image)
        outputs = self.session.run(None, {self.input_name: tensor})
        if not outputs:
            raise OcrModelError("识别模型没有返回输出")
        return self.decoder.decode(np.asarray(outputs[0]))


def load_dictionary(path: Path) -> list[str]:
    labels = path.read_text(encoding="utf-8").splitlines()
    if not labels:
        raise OcrModelError(f"OCR 字典为空：{path}")
    if " " not in labels:
        labels.append(" ")
    return labels


def load_default_recognizer() -> OnnxRecognizer:
    rec_path = model_path("PP-OCRv5_mobile_rec.onnx")
    dict_path = model_path("ppocrv5_dict.txt")
    if not rec_path.is_file() or not dict_path.is_file():
        raise OcrModelError("OCR 识别模型或字典缺失")
    session = ort.InferenceSession(str(rec_path), providers=["CPUExecutionProvider"])
    return OnnxRecognizer(session, CtcDecoder(load_dictionary(dict_path)))
