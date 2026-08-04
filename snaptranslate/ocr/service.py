import threading

from PIL import Image

from ..domain import EmptyInput, validate_text
from ..ocr_contract import OcrResult
from .detector import load_default_detector
from .geometry import sort_reading_order, warp_box
from .preprocess import likely_single_line, recognition_variants
from .recognizer import load_default_recognizer
from .types import RecognizedLine


def candidate_score(line: RecognizedLine) -> float:
    if not line.text.strip():
        return -1.0
    suspicious = sum(character in "�□?" for character in line.text)
    penalty = suspicious / max(1, len(line.text)) * 0.35
    return line.confidence - penalty


def _suspicious_ratio(text: str) -> float:
    return sum(character in "�□?" for character in text) / max(1, len(text))


class OcrService:
    def __init__(
        self,
        detector_factory=load_default_detector,
        recognizer_factory=load_default_recognizer,
        *,
        single_line_test=likely_single_line,
        warp=warp_box,
    ) -> None:
        self._detector_factory = detector_factory
        self._recognizer_factory = recognizer_factory
        self._single_line_test = single_line_test
        self._warp = warp
        self._detector = None
        self._recognizer = None
        self._lock = threading.RLock()

    def _get_recognizer(self):
        if self._recognizer is None:
            self._recognizer = self._recognizer_factory()
        return self._recognizer

    def _get_detector(self):
        if self._detector is None:
            self._detector = self._detector_factory()
        return self._detector

    def _best_line(self, image: Image.Image) -> RecognizedLine:
        recognizer = self._get_recognizer()
        results = [recognizer.recognize(candidate.image) for candidate in recognition_variants(image)]
        return max(results, key=candidate_score)

    def recognize(self, image: Image.Image) -> OcrResult:
        with self._lock:
            direct = self._best_line(image)
            if (
                self._single_line_test(image)
                and direct.confidence >= 0.88
                and _suspicious_ratio(direct.text) <= 0.10
            ):
                return OcrResult(validate_text(direct.text), direct.confidence)

            boxes = sort_reading_order(self._get_detector().detect(image))
            lines: list[RecognizedLine] = []
            for box in boxes:
                line = self._best_line(self._warp(image, box))
                if line.text.strip():
                    lines.append(line)
            if not lines:
                raise EmptyInput("未识别到文字")

            total_characters = sum(len(line.text) for line in lines)
            confidence = sum(line.confidence * len(line.text) for line in lines) / max(
                1, total_characters
            )
            if confidence < 0.45:
                raise EmptyInput("未识别到文字")
            text = validate_text("\n".join(line.text for line in lines))
            return OcrResult(text, confidence)

    def close(self) -> None:
        with self._lock:
            self._detector = None
            self._recognizer = None
