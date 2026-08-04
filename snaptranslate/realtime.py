from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import ctypes
from ctypes import wintypes
import math
import os
import threading
import time
from typing import Callable

from .mouse_input import DragClassifier, DragResult, MouseEvent, WinMouseHook
from .uia_selection import SelectionKind, SelectionProbe


IDC_IBEAM = 32513
CURSOR_SHOWING = 0x00000001


class _CursorInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hCursor", ctypes.c_void_p),
        ("ptScreenPos", wintypes.POINT),
    ]


class CursorClassifier:
    def __init__(self) -> None:
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._user32.LoadCursorW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self._user32.LoadCursorW.restype = ctypes.c_void_p
        self._ibeam = self._user32.LoadCursorW(None, ctypes.c_void_p(IDC_IBEAM))

    def is_ibeam(self) -> bool:
        info = _CursorInfo(cbSize=ctypes.sizeof(_CursorInfo))
        if not self._user32.GetCursorInfo(ctypes.byref(info)):
            return False
        return bool(info.flags & CURSOR_SHOWING) and info.hCursor == self._ibeam


class OwnProcessWindow:
    def __init__(self, process_id: int | None = None) -> None:
        self._process_id = process_id or os.getpid()
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._user32.WindowFromPoint.argtypes = [wintypes.POINT]
        self._user32.WindowFromPoint.restype = wintypes.HWND

    def __call__(self, point: tuple[int, int]) -> bool:
        window = self._user32.WindowFromPoint(wintypes.POINT(*point))
        if not window:
            return False
        process_id = wintypes.DWORD()
        self._user32.GetWindowThreadProcessId(window, ctypes.byref(process_id))
        return process_id.value == self._process_id


class RealtimeController:
    def __init__(
        self,
        probe=None,
        capture=None,
        cursor=None,
        own_window: Callable[[tuple[int, int]], bool] | None = None,
        on_text: Callable[[str], None] | None = None,
        on_pointer_down: Callable[[tuple[int, int]], None] | None = None,
        executor=None,
        clock: Callable[[], float] = time.monotonic,
        debounce_seconds: float = 0.18,
        hook_factory=None,
    ) -> None:
        self._probe = probe or SelectionProbe()
        self._capture = capture
        self._cursor = cursor or CursorClassifier()
        self._own_window = own_window or OwnProcessWindow()
        self._on_text = on_text or (lambda _text: None)
        self._on_pointer_down = on_pointer_down or (lambda _point: None)
        self._executor = executor or ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="realtime-selection",
        )
        self._clock = clock
        self._debounce_seconds = debounce_seconds
        self._classifier = DragClassifier()
        self._enabled = False
        self._pause_reasons: set[str] = set()
        self._last_release = -math.inf
        self._generation = 0
        self._lock = threading.Lock()
        self._hook_factory = hook_factory or WinMouseHook
        self._hook = None
        self._closed = False

    def start(self) -> None:
        if self._hook is not None or self._closed:
            return
        self._hook = self._hook_factory(self.handle_mouse_event)
        self._hook.start()

    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._enabled = enabled
            if not enabled:
                self._generation += 1

    def set_paused(self, reason: str, paused: bool) -> None:
        with self._lock:
            if paused:
                self._pause_reasons.add(reason)
                self._generation += 1
            else:
                self._pause_reasons.discard(reason)

    def handle_mouse_event(self, event: MouseEvent) -> None:
        if event.kind == "down":
            self._on_pointer_down((event.x, event.y))
        drag = self._classifier.feed(event)
        if drag is not None:
            self.handle_drag(drag)

    def _new_request(self) -> int | None:
        with self._lock:
            if not self._enabled or self._pause_reasons:
                return None
            self._generation += 1
            return self._generation

    def _request_is_current(self, request: int) -> bool:
        with self._lock:
            return (
                request == self._generation
                and self._enabled
                and not self._pause_reasons
                and not self._closed
            )

    def handle_drag(self, drag: DragResult) -> None:
        if self._own_window(drag.end):
            return
        request = self._new_request()
        if request is None:
            return
        now = self._clock()
        if now - self._last_release < self._debounce_seconds:
            return
        self._last_release = now
        self._executor.submit(self._resolve_drag, request, drag.end)

    def _resolve_drag(self, request: int, point: tuple[int, int]) -> None:
        result = self._probe.query(point)
        text = ""
        if result.kind is SelectionKind.TEXT:
            text = result.text
        elif result.kind in (SelectionKind.UNSUPPORTED, SelectionKind.TIMEOUT):
            if self._cursor.is_ibeam() and self._capture is not None:
                captured = self._capture.capture()
                if isinstance(captured, str):
                    text = captured
        if text and self._request_is_current(request):
            self._on_text(text)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._generation += 1
        if self._hook is not None:
            self._hook.close()
        close_probe = getattr(self._probe, "close", None)
        if close_probe is not None:
            close_probe()
        self._executor.shutdown(wait=False, cancel_futures=True)
