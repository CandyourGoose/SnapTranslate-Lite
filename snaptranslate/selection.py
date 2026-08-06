import ctypes
import threading
import time

import pyperclip

from .clipboard_capture import ClipboardBackend


VK_CONTROL = 0x11
VK_C = 0x43
KEYEVENTF_KEYUP = 0x0002


class Keyboard:
    def __init__(self) -> None:
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)

    def copy_selection(self) -> None:
        self._user32.keybd_event(VK_CONTROL, 0, 0, 0)
        self._user32.keybd_event(VK_C, 0, 0, 0)
        self._user32.keybd_event(VK_C, 0, KEYEVENTF_KEYUP, 0)
        self._user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)


class SelectionCapture:
    def __init__(self, clipboard=None, keyboard=None, sleep=time.sleep) -> None:
        self._clipboard = clipboard or ClipboardBackend()
        self._keyboard = keyboard or Keyboard()
        self._sleep = sleep
        self._capture_lock = threading.Lock()

    def capture(self) -> str:
        with self._capture_lock:
            return self._capture_once()

    def _capture_once(self) -> str:
        try:
            before = self._clipboard.sequence_number()
            self._keyboard.copy_selection()
            for _ in range(20):
                if self._clipboard.sequence_number() != before:
                    return self._clipboard.read_text()
                self._sleep(0.03)
        except (OSError, RuntimeError, pyperclip.PyperclipException):
            return ""
        return ""
