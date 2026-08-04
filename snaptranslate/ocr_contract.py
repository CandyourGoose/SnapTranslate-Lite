from dataclasses import dataclass
from typing import Protocol

from PIL.Image import Image


@dataclass(frozen=True)
class OcrResult:
    text: str
    confidence: float


class OcrPort(Protocol):
    def recognize(self, image: Image) -> OcrResult: ...

    def close(self) -> None: ...


class UnavailableOcr:
    def recognize(self, image: Image) -> OcrResult:
        raise RuntimeError("OCR 模块尚未安装")

    def close(self) -> None:
        return None

