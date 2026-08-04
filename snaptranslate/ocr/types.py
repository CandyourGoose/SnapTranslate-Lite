from dataclasses import dataclass

from PIL.Image import Image


@dataclass(frozen=True)
class LineCandidate:
    image: Image
    scale: float


@dataclass(frozen=True)
class RecognizedLine:
    text: str
    confidence: float
    box: tuple[tuple[float, float], ...] = ()

