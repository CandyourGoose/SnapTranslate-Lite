from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import queue
import threading
import time
from typing import Callable


WH_MOUSE_LL = 14
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_QUIT = 0x0012


@dataclass(frozen=True)
class MouseEvent:
    kind: str
    x: int
    y: int
    timestamp: float


@dataclass(frozen=True)
class DragResult:
    start: tuple[int, int]
    end: tuple[int, int]


class DragClassifier:
    def __init__(self, min_distance: int = 6) -> None:
        self._minimum_squared = min_distance * min_distance
        self._start: tuple[int, int] | None = None
        self._dragged = False

    def feed(self, event: MouseEvent) -> DragResult | None:
        if event.kind == "down":
            self._start = (event.x, event.y)
            self._dragged = False
            return None
        if self._start is None:
            return None
        if event.kind == "move":
            dx = event.x - self._start[0]
            dy = event.y - self._start[1]
            if dx * dx + dy * dy >= self._minimum_squared:
                self._dragged = True
            return None
        if event.kind != "up":
            return None

        start = self._start
        dragged = self._dragged
        self._start = None
        self._dragged = False
        if not dragged:
            return None
        return DragResult(start, (event.x, event.y))


class _MouseHookData(ctypes.Structure):
    _fields_ = [
        ("pt", wintypes.POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


_HOOK_CALLBACK = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t,
    ctypes.c_int,
    wintypes.WPARAM,
    wintypes.LPARAM,
)


class WinMouseHook:
    def __init__(self, on_event: Callable[[MouseEvent], None]) -> None:
        self._on_event = on_event
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._user32.SetWindowsHookExW.argtypes = [
            ctypes.c_int,
            _HOOK_CALLBACK,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        self._user32.SetWindowsHookExW.restype = ctypes.c_void_p
        self._user32.CallNextHookEx.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        self._user32.CallNextHookEx.restype = ctypes.c_ssize_t
        self._user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
        self._user32.UnhookWindowsHookEx.restype = wintypes.BOOL
        self._kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        self._kernel32.GetModuleHandleW.restype = ctypes.c_void_p
        self._events: queue.Queue[MouseEvent | None] = queue.Queue()
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._hook_thread: threading.Thread | None = None
        self._worker_thread: threading.Thread | None = None
        self._hook = None
        self._callback = _HOOK_CALLBACK(self._hook_callback)
        self._thread_id = 0
        self._left_down = False

    def _hook_callback(self, code, message, data_pointer):
        if code >= 0:
            kind = None
            if message == WM_LBUTTONDOWN:
                self._left_down = True
                kind = "down"
            elif message == WM_LBUTTONUP:
                kind = "up"
                self._left_down = False
            elif message == WM_MOUSEMOVE and self._left_down:
                kind = "move"
            if kind is not None:
                data = ctypes.cast(
                    data_pointer,
                    ctypes.POINTER(_MouseHookData),
                ).contents
                self._events.put(
                    MouseEvent(kind, data.pt.x, data.pt.y, time.monotonic())
                )
        return self._user32.CallNextHookEx(None, code, message, data_pointer)

    def _hook_loop(self) -> None:
        self._thread_id = int(self._kernel32.GetCurrentThreadId())
        self._hook = self._user32.SetWindowsHookExW(
            WH_MOUSE_LL,
            self._callback,
            self._kernel32.GetModuleHandleW(None),
            0,
        )
        self._ready.set()
        if not self._hook:
            return
        message = wintypes.MSG()
        try:
            while self._user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                self._user32.TranslateMessage(ctypes.byref(message))
                self._user32.DispatchMessageW(ctypes.byref(message))
        finally:
            self._user32.UnhookWindowsHookEx(self._hook)
            self._hook = None

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            event = self._events.get()
            if event is None:
                return
            self._on_event(event)

    def start(self) -> None:
        if self._hook_thread is not None or self._stop.is_set():
            return
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="mouse-input-worker",
            daemon=True,
        )
        self._hook_thread = threading.Thread(
            target=self._hook_loop,
            name="global-mouse-hook",
            daemon=True,
        )
        self._worker_thread.start()
        self._hook_thread.start()
        self._ready.wait(timeout=1.0)

    def close(self) -> None:
        if self._stop.is_set():
            return
        self._stop.set()
        if self._thread_id:
            self._user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        self._events.put(None)
        if self._hook_thread is not None:
            self._hook_thread.join(timeout=1.0)
        if self._worker_thread is not None:
            self._worker_thread.join(timeout=1.0)
