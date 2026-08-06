from __future__ import annotations

import ctypes

import pyperclip


class ClipboardBackend:
    def __init__(self) -> None:
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)

    def sequence_number(self) -> int:
        return int(self._user32.GetClipboardSequenceNumber())

    @staticmethod
    def read_text() -> str:
        value = pyperclip.paste()
        return value if isinstance(value, str) else ""
