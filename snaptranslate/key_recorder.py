from __future__ import annotations

import ctypes
import threading
import time
from typing import Callable, Protocol

from .hotkeys import parse_hotkey


VK_TAB = 0x09
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_LSHIFT = 0xA0
VK_RSHIFT = 0xA1
VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3
VK_LMENU = 0xA4
VK_RMENU = 0xA5

_MODIFIER_NAMES = {
    VK_TAB: "tab",
    VK_SHIFT: "shift",
    VK_LSHIFT: "shift",
    VK_RSHIFT: "shift",
    VK_CONTROL: "ctrl",
    VK_LCONTROL: "ctrl",
    VK_RCONTROL: "ctrl",
    VK_MENU: "alt",
    VK_LMENU: "alt",
    VK_RMENU: "alt",
    VK_LWIN: "win",
    VK_RWIN: "win",
}
_MODIFIER_ORDER = ("ctrl", "alt", "shift", "win", "tab")
_SCANNED_KEYS = tuple(range(1, 256))


class KeySource(Protocol):
    def pressed_keys(self) -> set[int]: ...


class WinKeySource:
    def __init__(self) -> None:
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)

    def pressed_keys(self) -> set[int]:
        return {
            virtual_key
            for virtual_key in _SCANNED_KEYS
            if self._user32.GetAsyncKeyState(virtual_key) & 0x8000
        }


def _ordinary_token(virtual_key: int) -> str | None:
    if ord("A") <= virtual_key <= ord("Z"):
        return chr(virtual_key).lower()
    if ord("0") <= virtual_key <= ord("9"):
        return chr(virtual_key)
    if 0x70 <= virtual_key <= 0x7B:
        return f"f{virtual_key - 0x70 + 1}"
    return None


class HotkeyChordDetector:
    def __init__(self) -> None:
        self._previous: set[int] = set()

    def reset(self) -> None:
        self._previous.clear()

    def feed(self, pressed: set[int]) -> tuple[str | None, str | None] | None:
        newly_pressed = pressed - self._previous
        self._previous = set(pressed)
        ordinary_keys = sorted(key for key in newly_pressed if key not in _MODIFIER_NAMES)
        if not ordinary_keys:
            return None

        virtual_key = ordinary_keys[0]
        token = _ordinary_token(virtual_key)
        if token is None:
            return None, f"不支持的按键：0x{virtual_key:02X}"

        held_modifiers = {
            name for key, name in _MODIFIER_NAMES.items() if key in pressed
        }
        ordered = [name for name in _MODIFIER_ORDER if name in held_modifiers]
        try:
            canonical = parse_hotkey("+".join([*ordered, token])).canonical
        except ValueError as exc:
            return None, str(exc)
        return canonical, None


class PhysicalKeyRecorder:
    def __init__(
        self,
        source: KeySource | None = None,
        dispatch: Callable[[Callable[[], None]], None] | None = None,
        poll_interval: float = 0.01,
        autostart: bool | None = None,
    ) -> None:
        self._source = source or WinKeySource()
        self._dispatch = dispatch or (lambda function: function())
        self._poll_interval = poll_interval
        self._detector = HotkeyChordDetector()
        self._callback: Callable[[str | None, str | None], None] | None = None
        self._active = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        use_thread = source is None if autostart is None else autostart
        if use_thread:
            self._thread = threading.Thread(
                target=self._run,
                name="physical-key-recorder",
                daemon=True,
            )
            self._thread.start()

    @property
    def active(self) -> bool:
        return self._active

    def start(self, callback: Callable[[str | None, str | None], None]) -> None:
        self.cancel()
        self._detector.reset()
        self._callback = callback
        self._active = True

    def cancel(self) -> None:
        self._active = False
        self._callback = None
        self._detector.reset()

    def poll_once(self) -> None:
        if not self._active:
            return
        result = self._detector.feed(self._source.pressed_keys())
        if result is None:
            return
        value, error = result
        callback = self._callback
        if callback is None:
            return
        if value is not None:
            self._active = False
            self._callback = None
        self._dispatch(lambda: callback(value, error))

    def _run(self) -> None:
        while not self._stop.wait(self._poll_interval):
            self.poll_once()

    def close(self) -> None:
        self.cancel()
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
