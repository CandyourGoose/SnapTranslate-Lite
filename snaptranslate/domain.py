from dataclasses import dataclass
from enum import StrEnum


MAX_TEXT_LENGTH = 120


class TranslationSource(StrEnum):
    AUTO = "auto"
    MYMEMORY = "mymemory"


class PopupContent(StrEnum):
    BOTH = "both"
    TRANSLATION_ONLY = "translation_only"


class UserInputError(ValueError):
    pass


class EmptyInput(UserInputError):
    pass


class InputTooLong(UserInputError):
    pass


class TranslationFailure(RuntimeError):
    pass


@dataclass(frozen=True)
class TranslationResult:
    text: str
    source: str


def normalize_text(text: str) -> str:
    normalized_lines = (
        " ".join(line.split())
        for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    )
    return "\n".join(line for line in normalized_lines if line).strip()


def validate_text(text: str) -> str:
    normalized = normalize_text(text)
    if not normalized:
        raise EmptyInput("未获取到文字")
    if len(normalized) > MAX_TEXT_LENGTH:
        raise InputTooLong(f"文字超过 {MAX_TEXT_LENGTH} 个字符")
    return normalized

