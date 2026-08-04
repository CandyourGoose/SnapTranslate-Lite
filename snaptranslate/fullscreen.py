from __future__ import annotations

import ctypes
import threading
from typing import Callable


QUNS_RUNNING_D3D_FULL_SCREEN = 3


def query_notification_state() -> int:
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    function = shell32.SHQueryUserNotificationState
    function.argtypes = [ctypes.POINTER(ctypes.c_int)]
    function.restype = ctypes.c_long
    state = ctypes.c_int()
    result = function(ctypes.byref(state))
    if result != 0:
        raise OSError(result, "SHQueryUserNotificationState failed")
    return state.value


class ExclusiveFullscreenMonitor:
    def __init__(
        self,
        query: Callable[[], int] = query_notification_state,
        on_change: Callable[[bool], None] | None = None,
        interval: float = 0.5,
    ) -> None:
        self._query = query
        self._on_change = on_change or (lambda _active: None)
        self._interval = interval
        self._active = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def closed(self) -> bool:
        return self._stop.is_set()

    def poll_once(self) -> None:
        try:
            active = self._query() == QUNS_RUNNING_D3D_FULL_SCREEN
        except (OSError, RuntimeError):
            return
        if active == self._active:
            return
        self._active = active
        self._on_change(active)

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            self.poll_once()

    def start(self) -> None:
        if self._thread is not None or self._stop.is_set():
            return
        self._thread = threading.Thread(
            target=self._run,
            name="exclusive-fullscreen-monitor",
            daemon=True,
        )
        self._thread.start()

    def close(self) -> None:
        if self._stop.is_set():
            return
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
