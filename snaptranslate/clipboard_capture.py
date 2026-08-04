from __future__ import annotations

import ctypes
from dataclasses import dataclass
import time

import pyperclip


S_OK = 0
S_FALSE = 1


def _failed(hresult: int) -> bool:
    return hresult < 0


@dataclass
class ClipboardSnapshot:
    data_object: int | None
    ole_initialized: bool = True


class ClipboardBackend:
    def __init__(self, retries: int = 5, retry_delay: float = 0.01) -> None:
        self._retries = retries
        self._retry_delay = retry_delay
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._ole32 = ctypes.OleDLL("ole32", use_last_error=True)
        self._ole32.OleInitialize.argtypes = [ctypes.c_void_p]
        self._ole32.OleInitialize.restype = ctypes.c_long
        self._ole32.OleUninitialize.argtypes = []
        self._ole32.OleGetClipboard.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        self._ole32.OleGetClipboard.restype = ctypes.c_long
        self._ole32.OleSetClipboard.argtypes = [ctypes.c_void_p]
        self._ole32.OleSetClipboard.restype = ctypes.c_long
        self._ole32.OleFlushClipboard.argtypes = []
        self._ole32.OleFlushClipboard.restype = ctypes.c_long

    def sequence_number(self) -> int:
        return int(self._user32.GetClipboardSequenceNumber())

    def _initialize_ole(self) -> None:
        result = int(self._ole32.OleInitialize(None))
        if result not in (S_OK, S_FALSE):
            raise OSError(result, "OleInitialize failed")

    def hold_current(self) -> ClipboardSnapshot:
        self._initialize_ole()
        if self._user32.CountClipboardFormats() == 0:
            return ClipboardSnapshot(None)

        try:
            self._retry_ole_call(self._ole32.OleFlushClipboard, "OleFlushClipboard")
            data_object = ctypes.c_void_p()
            for attempt in range(self._retries):
                result = int(self._ole32.OleGetClipboard(ctypes.byref(data_object)))
                if not _failed(result) and data_object.value:
                    return ClipboardSnapshot(int(data_object.value))
                if attempt + 1 < self._retries:
                    time.sleep(self._retry_delay)
            raise OSError(result, "OleGetClipboard failed")
        except Exception:
            self._ole32.OleUninitialize()
            raise

    def _retry_ole_call(self, operation, name: str) -> None:
        result = S_OK
        for attempt in range(self._retries):
            result = int(operation())
            if not _failed(result):
                return
            if attempt + 1 < self._retries:
                time.sleep(self._retry_delay)
        raise OSError(result, f"{name} failed")

    @staticmethod
    def _release_data_object(pointer: int) -> None:
        object_pointer = ctypes.c_void_p(pointer)
        vtable = ctypes.cast(
            object_pointer,
            ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)),
        ).contents
        release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])
        release(object_pointer)

    def restore(self, snapshot: ClipboardSnapshot) -> None:
        pointer = ctypes.c_void_p(snapshot.data_object) if snapshot.data_object else None
        last_result = S_OK
        try:
            for attempt in range(self._retries):
                last_result = int(self._ole32.OleSetClipboard(pointer))
                if not _failed(last_result):
                    self._retry_ole_call(
                        self._ole32.OleFlushClipboard,
                        "OleFlushClipboard",
                    )
                    return
                if attempt + 1 < self._retries:
                    time.sleep(self._retry_delay)
            raise OSError(last_result, "OleSetClipboard failed")
        finally:
            if snapshot.data_object:
                self._release_data_object(snapshot.data_object)
                snapshot.data_object = None
            if snapshot.ole_initialized:
                self._ole32.OleUninitialize()
                snapshot.ole_initialized = False

    @staticmethod
    def read_text() -> str:
        value = pyperclip.paste()
        return value if isinstance(value, str) else ""
