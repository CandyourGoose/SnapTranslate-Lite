import ctypes
from ctypes import wintypes
import threading


ERROR_ALREADY_EXISTS = 183
WAIT_OBJECT_0 = 0


class KernelApi:
    def __init__(self) -> None:
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
        self.kernel32.CreateMutexW.restype = wintypes.HANDLE
        self.kernel32.CreateEventW.argtypes = (
            ctypes.c_void_p,
            wintypes.BOOL,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        )
        self.kernel32.CreateEventW.restype = wintypes.HANDLE
        self.kernel32.OpenEventW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
        self.kernel32.OpenEventW.restype = wintypes.HANDLE
        self.kernel32.SetEvent.argtypes = (wintypes.HANDLE,)
        self.kernel32.SetEvent.restype = wintypes.BOOL
        self.kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        self.kernel32.WaitForSingleObject.restype = wintypes.DWORD
        self.kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)

    def create_mutex(self, name: str):
        ctypes.set_last_error(0)
        handle = self.kernel32.CreateMutexW(None, False, name)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        return handle, ctypes.get_last_error() == ERROR_ALREADY_EXISTS

    def create_event(self, name: str):
        handle = self.kernel32.CreateEventW(None, False, False, name)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        return handle

    def open_event(self, name: str):
        return self.kernel32.OpenEventW(0x0002, False, name) or None

    def set_event(self, handle) -> None:
        if not self.kernel32.SetEvent(handle):
            raise ctypes.WinError(ctypes.get_last_error())

    def wait_event(self, handle, timeout_ms: int) -> bool:
        return self.kernel32.WaitForSingleObject(handle, timeout_ms) == WAIT_OBJECT_0

    def close_handle(self, handle) -> None:
        if handle:
            self.kernel32.CloseHandle(handle)


class SingleInstance:
    def __init__(self, api=None, suffix: str = "Lite") -> None:
        self._api = api or KernelApi()
        self._mutex_name = f"Local\\SnapTranslate-{suffix}-Mutex"
        self._event_name = f"Local\\SnapTranslate-{suffix}-Wake"
        self._mutex = None
        self._event = None
        self._owner = False
        self._stop = threading.Event()
        self._waiter: threading.Thread | None = None

    def acquire(self) -> bool:
        if self._mutex is not None:
            return self._owner
        self._mutex, already_exists = self._api.create_mutex(self._mutex_name)
        self._owner = not already_exists
        if self._owner:
            self._event = self._api.create_event(self._event_name)
        return self._owner

    def signal_existing(self) -> None:
        handle = self._api.open_event(self._event_name)
        if handle is None:
            return
        try:
            self._api.set_event(handle)
        finally:
            self._api.close_handle(handle)

    def wait_for_wake(self, callback) -> None:
        if not self._owner or self._event is None or self._waiter is not None:
            return

        def wait_loop() -> None:
            while not self._stop.is_set():
                if self._api.wait_event(self._event, 250):
                    callback()

        self._waiter = threading.Thread(target=wait_loop, name="instance-wake", daemon=True)
        self._waiter.start()

    def close(self) -> None:
        self._stop.set()
        if self._event is not None:
            self._api.close_handle(self._event)
            self._event = None
        if self._mutex is not None:
            self._api.close_handle(self._mutex)
            self._mutex = None
        self._owner = False
