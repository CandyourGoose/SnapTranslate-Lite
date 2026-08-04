from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass


MONITOR_DEFAULTTONEAREST = 2
PER_MONITOR_AWARE = 2
PER_MONITOR_AWARE_V2 = -4
BASE_DPI = 96
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


@dataclass(frozen=True)
class MonitorSnapshot:
    bounds: Rect
    work_area: Rect
    dpi: int

    @property
    def scale(self) -> float:
        return max(1.0, self.dpi / BASE_DPI)


class _MonitorInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


class WinDisplayApi:
    def __init__(self) -> None:
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)

    def monitor_from_point(self, point: tuple[int, int]):
        function = self._user32.MonitorFromPoint
        function.argtypes = [wintypes.POINT, wintypes.DWORD]
        function.restype = ctypes.c_void_p
        return function(
            wintypes.POINT(*point),
            MONITOR_DEFAULTTONEAREST,
        )

    def monitor_snapshot(self, handle) -> tuple[
        tuple[int, int, int, int], tuple[int, int, int, int], int
    ]:
        info = _MonitorInfo(cbSize=ctypes.sizeof(_MonitorInfo))
        monitor_info = self._user32.GetMonitorInfoW
        monitor_info.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_MonitorInfo),
        ]
        monitor_info.restype = wintypes.BOOL
        if not monitor_info(handle, ctypes.byref(info)):
            raise OSError(ctypes.get_last_error(), "GetMonitorInfoW failed")
        x_dpi = wintypes.UINT()
        y_dpi = wintypes.UINT()
        dpi = BASE_DPI
        try:
            shcore = ctypes.WinDLL("shcore", use_last_error=True)
            get_dpi = shcore.GetDpiForMonitor
            get_dpi.argtypes = [
                ctypes.c_void_p,
                ctypes.c_int,
                ctypes.POINTER(wintypes.UINT),
                ctypes.POINTER(wintypes.UINT),
            ]
            get_dpi.restype = ctypes.c_long
            if get_dpi(handle, 0, ctypes.byref(x_dpi), ctypes.byref(y_dpi)) == 0:
                dpi = int(x_dpi.value)
        except (AttributeError, OSError):
            pass
        monitor = info.rcMonitor
        work = info.rcWork
        return (
            (monitor.left, monitor.top, monitor.right, monitor.bottom),
            (work.left, work.top, work.right, work.bottom),
            dpi,
        )


class NativeWindowApi:
    def __init__(self) -> None:
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._gdi32 = None

    def _gdi(self):
        if self._gdi32 is None:
            self._gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        return self._gdi32

    def parent(self, client_handle: int) -> int:
        function = self._user32.GetParent
        function.argtypes = [wintypes.HWND]
        function.restype = wintypes.HWND
        ctypes.set_last_error(0)
        parent_handle = int(function(client_handle) or 0)
        if parent_handle:
            return parent_handle
        error = ctypes.get_last_error()
        if error:
            raise OSError(error, "GetParent failed")
        return client_handle

    def window_dpi(self, handle: int) -> int:
        function = self._user32.GetDpiForWindow
        function.argtypes = [wintypes.HWND]
        function.restype = wintypes.UINT
        dpi = int(function(handle))
        if not dpi:
            raise OSError(ctypes.get_last_error(), "GetDpiForWindow failed")
        return dpi

    def set_position(self, handle: int, rect: Rect) -> bool:
        try:
            function = self._user32.SetWindowPos
            function.argtypes = [
                wintypes.HWND,
                wintypes.HWND,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                wintypes.UINT,
            ]
            function.restype = wintypes.BOOL
            return bool(
                function(
                    handle,
                    None,
                    rect.left,
                    rect.top,
                    rect.width,
                    rect.height,
                    SWP_NOACTIVATE | SWP_SHOWWINDOW,
                )
            )
        except (AttributeError, OSError):
            return False

    def round_region(self, width: int, height: int, diameter: int):
        try:
            function = self._gdi().CreateRoundRectRgn
            function.argtypes = [
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
            ]
            function.restype = wintypes.HRGN
            return function(
                0,
                0,
                width + 1,
                height + 1,
                diameter,
                diameter,
            )
        except (AttributeError, OSError):
            return None

    def set_region(self, handle: int, region) -> bool:
        try:
            function = self._user32.SetWindowRgn
            function.argtypes = [wintypes.HWND, wintypes.HRGN, wintypes.BOOL]
            function.restype = ctypes.c_int
            return bool(function(handle, region, True))
        except (AttributeError, OSError):
            return False

    def delete_region(self, region) -> None:
        try:
            function = self._gdi().DeleteObject
            function.argtypes = [wintypes.HGDIOBJ]
            function.restype = wintypes.BOOL
            function(region)
        except (AttributeError, OSError):
            pass


def cursor_position() -> tuple[int, int]:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    point = wintypes.POINT()
    if not user32.GetCursorPos(ctypes.byref(point)):
        raise OSError(ctypes.get_last_error(), "GetCursorPos failed")
    return point.x, point.y


def monitor_snapshot_from_point(
    point: tuple[int, int],
    api=None,
) -> MonitorSnapshot:
    display = api or WinDisplayApi()
    handle = display.monitor_from_point(point)
    if not handle:
        raise OSError("MonitorFromPoint failed")
    bounds, work_area, dpi = display.monitor_snapshot(handle)
    return MonitorSnapshot(Rect(*bounds), Rect(*work_area), dpi)


def monitor_rect_from_point(
    point: tuple[int, int],
    api=None,
) -> Rect:
    return monitor_snapshot_from_point(point, api).bounds


def native_toplevel_handle(window, api=None) -> int:
    native = api or NativeWindowApi()
    return native.parent(int(window.winfo_id()))


def toplevel_dpi_scale(window, api=None, fallback: float = 1.0) -> float:
    try:
        fallback_scale = max(1.0, float(fallback))
    except (TypeError, ValueError):
        fallback_scale = 1.0
    try:
        native = api or NativeWindowApi()
        return max(
            1.0,
            native.window_dpi(native_toplevel_handle(window, native)) / BASE_DPI,
        )
    except Exception:
        return fallback_scale


def place_toplevel_physical(window, rect: Rect, api=None) -> bool:
    try:
        native = api or NativeWindowApi()
        return native.set_position(native_toplevel_handle(window, native), rect)
    except Exception:
        return False


def apply_toplevel_rounding(
    window,
    width: int,
    height: int,
    radius: int,
    api=None,
) -> bool:
    native = None
    region = None
    try:
        native = api or NativeWindowApi()
        region = native.round_region(width, height, radius * 2)
        if not region:
            return False
        if native.set_region(native_toplevel_handle(window, native), region):
            return True
    except Exception:
        pass
    if region and native is not None:
        try:
            native.delete_region(region)
        except Exception:
            pass
    return False


def enable_per_monitor_dpi() -> None:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    try:
        if user32.SetProcessDpiAwarenessContext(
            ctypes.c_void_p(PER_MONITOR_AWARE_V2)
        ):
            return
    except AttributeError:
        pass
    try:
        shcore = ctypes.WinDLL("shcore", use_last_error=True)
        if shcore.SetProcessDpiAwareness(PER_MONITOR_AWARE) == 0:
            return
    except (AttributeError, OSError):
        pass
    try:
        user32.SetProcessDPIAware()
    except AttributeError:
        pass
