from collections.abc import Mapping
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import queue
import re
import threading
import time


MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
VK_TAB = 0x09
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_LSHIFT = 0xA0
VK_RSHIFT = 0xA1
VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3
VK_LMENU = 0xA4
VK_RMENU = 0xA5

_MODIFIER_BITS = {
    "alt": MOD_ALT,
    "ctrl": MOD_CONTROL,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
}
_PHYSICAL_MODIFIER_KEYS = {
    MOD_ALT: (VK_LMENU, VK_RMENU),
    MOD_CONTROL: (VK_LCONTROL, VK_RCONTROL),
    MOD_SHIFT: (VK_LSHIFT, VK_RSHIFT),
    MOD_WIN: (VK_LWIN, VK_RWIN),
}
_MODIFIER_ORDER = ("ctrl", "alt", "shift", "win", "tab")
_DISPLAY_NAMES = {
    "ctrl": "Ctrl",
    "alt": "Alt",
    "shift": "Shift",
    "win": "Win",
    "tab": "Tab",
}
_ACTION_NAMES = {
    "translate": "划词翻译",
    "realtime": "实时翻译",
    "ocr": "OCR 翻译",
}


class HotkeyConflict(RuntimeError):
    pass


@dataclass(frozen=True)
class Hotkey:
    canonical: str
    modifiers: int
    virtual_key: int
    uses_polling: bool
    polling_keys: tuple[int, ...]


def _virtual_key(token: str) -> int:
    if len(token) == 1 and token.isalnum():
        return ord(token.upper())
    if re.fullmatch(r"f(?:[1-9]|1[0-2])", token):
        return 0x70 + int(token[1:]) - 1
    raise ValueError(f"不支持的按键：{token}")


def parse_hotkey(text: str) -> Hotkey:
    tokens = [part.strip().lower() for part in text.split("+") if part.strip()]
    if len(tokens) != len(set(tokens)):
        raise ValueError("快捷键中存在重复按键")
    modifiers = [token for token in tokens if token in _MODIFIER_ORDER]
    ordinary = [token for token in tokens if token not in _MODIFIER_ORDER]
    if not modifiers:
        raise ValueError("快捷键必须包含修饰键")
    if len(ordinary) != 1:
        raise ValueError("快捷键必须包含一个普通按键")

    ordered_modifiers = [name for name in _MODIFIER_ORDER if name in modifiers]
    key_token = ordinary[0]
    virtual_key = _virtual_key(key_token)
    modifier_bits = sum(_MODIFIER_BITS.get(name, 0) for name in ordered_modifiers)
    uses_polling = "tab" in ordered_modifiers
    polling_keys = tuple(
        [*([VK_TAB] if uses_polling else []), virtual_key]
    )
    return Hotkey(
        canonical="+".join([*ordered_modifiers, key_token]),
        modifiers=modifier_bits,
        virtual_key=virtual_key,
        uses_polling=uses_polling,
        polling_keys=polling_keys,
    )


def format_hotkey(value: str) -> str:
    canonical = parse_hotkey(value).canonical
    return "+".join(
        _DISPLAY_NAMES.get(token, token.upper())
        for token in canonical.split("+")
    )


class HotkeyManager:
    def __init__(self, api, on_action=None) -> None:
        self._api = api
        self._on_action = on_action or (lambda _action: None)
        self._parsed: dict[str, Hotkey] = {}
        self._identifiers: dict[str, int] = {}
        self._pause_reasons: set[str] = set()

    @property
    def bindings(self) -> dict[str, str]:
        return {action: hotkey.canonical for action, hotkey in self._parsed.items()}

    def _identifier(self, action: str) -> int:
        if action not in self._identifiers:
            self._identifiers[action] = len(self._identifiers) + 1
        return self._identifiers[action]

    def _unregister(self, bindings: Mapping[str, Hotkey]) -> None:
        for action in bindings:
            self._api.unregister(self._identifier(action))

    def _register_all(self, bindings: Mapping[str, Hotkey]) -> tuple[bool, list[str]]:
        registered: list[str] = []
        for action, hotkey in bindings.items():
            if not self._api.register(self._identifier(action), hotkey):
                return False, registered
            registered.append(action)
        return True, registered

    def replace(self, bindings: Mapping[str, str]) -> None:
        proposed = {action: parse_hotkey(value) for action, value in bindings.items()}
        seen: dict[str, str] = {}
        for action, hotkey in proposed.items():
            previous_action = seen.get(hotkey.canonical)
            if previous_action is not None:
                current_name = _ACTION_NAMES.get(action, action)
                previous_name = _ACTION_NAMES.get(previous_action, previous_action)
                raise HotkeyConflict(f"{current_name}与{previous_name}快捷键不能相同")
            seen[hotkey.canonical] = action

        if self._pause_reasons:
            success, registered = self._register_all(proposed)
            for action in registered:
                self._api.unregister(self._identifier(action))
            if not success:
                raise HotkeyConflict("快捷键已被其他程序占用，已恢复原设置")
            self._parsed = proposed
            return

        previous = dict(self._parsed)
        self._unregister(previous)
        success, registered = self._register_all(proposed)
        if success:
            self._parsed = proposed
            return

        for action in registered:
            self._api.unregister(self._identifier(action))
        restored, _ = self._register_all(previous)
        if not restored:
            self._parsed = {}
            raise HotkeyConflict("新快捷键注册失败，旧快捷键也无法恢复")
        self._parsed = previous
        raise HotkeyConflict("快捷键已被其他程序占用，已恢复原设置")

    def set_paused(self, reason: str, paused: bool) -> None:
        if paused:
            if reason in self._pause_reasons:
                return
            if not self._pause_reasons:
                self._unregister(self._parsed)
            self._pause_reasons.add(reason)
            return

        if reason not in self._pause_reasons:
            return
        self._pause_reasons.remove(reason)
        if self._pause_reasons:
            return

        success, registered = self._register_all(self._parsed)
        if success:
            return
        for action in registered:
            self._api.unregister(self._identifier(action))
        self._pause_reasons.add(reason)
        raise HotkeyConflict("恢复快捷键失败，程序将继续暂停快捷键")

    def close(self) -> None:
        self._unregister(self._parsed)
        self._parsed.clear()
        close_api = getattr(self._api, "close", None)
        if close_api is not None:
            close_api()

    def trigger(self, identifier: int) -> None:
        for action, action_identifier in self._identifiers.items():
            if action_identifier == identifier and action in self._parsed:
                self._on_action(action)
                return


class WinHotkeyApi:
    WM_HOTKEY = 0x0312
    PM_REMOVE = 0x0001

    def __init__(self, callback=None) -> None:
        self._callback = callback or (lambda _identifier: None)
        self._commands: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._polling: dict[int, Hotkey] = {}
        self._poll_pressed: set[int] = set()
        self._ready = threading.Event()
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._thread = threading.Thread(target=self._run, name="global-hotkeys", daemon=True)
        self._thread.start()
        self._ready.wait(2.0)

    def set_callback(self, callback) -> None:
        self._callback = callback

    def _invoke(self, operation: str, *args):
        done = threading.Event()
        result: list[object] = []
        self._commands.put((operation, args, done, result))
        if not done.wait(2.0):
            return False
        return result[0] if result else True

    def register(self, identifier: int, hotkey: Hotkey) -> bool:
        return bool(self._invoke("register", identifier, hotkey))

    def unregister(self, identifier: int) -> None:
        self._invoke("unregister", identifier)

    def _drain_commands(self) -> None:
        while True:
            try:
                operation, args, done, result = self._commands.get_nowait()
            except queue.Empty:
                return
            try:
                if operation == "register":
                    identifier, hotkey = args
                    if hotkey.uses_polling:
                        self._polling[identifier] = hotkey
                        result.append(True)
                    else:
                        result.append(
                            bool(
                                self._user32.RegisterHotKey(
                                    None,
                                    identifier,
                                    hotkey.modifiers,
                                    hotkey.virtual_key,
                                )
                            )
                        )
                elif operation == "unregister":
                    identifier = args[0]
                    self._polling.pop(identifier, None)
                    self._poll_pressed.discard(identifier)
                    self._user32.UnregisterHotKey(None, identifier)
                    result.append(True)
            finally:
                done.set()

    def _poll_chords(self) -> None:
        modifier_states = {
            modifier: any(
                self._user32.GetAsyncKeyState(key) & 0x8000
                for key in physical_keys
            )
            for modifier, physical_keys in _PHYSICAL_MODIFIER_KEYS.items()
        }
        for identifier, hotkey in tuple(self._polling.items()):
            modifiers_pressed = all(
                bool(hotkey.modifiers & modifier) == pressed
                for modifier, pressed in modifier_states.items()
            )
            pressed = modifiers_pressed and all(
                self._user32.GetAsyncKeyState(key) & 0x8000
                for key in hotkey.polling_keys
            )
            if pressed and identifier not in self._poll_pressed:
                self._poll_pressed.add(identifier)
                self._callback(identifier)
            elif not pressed:
                self._poll_pressed.discard(identifier)

    def _run(self) -> None:
        msg = wintypes.MSG()
        self._ready.set()
        while not self._stop.is_set():
            self._drain_commands()
            while self._user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, self.PM_REMOVE):
                if msg.message == self.WM_HOTKEY:
                    self._callback(int(msg.wParam))
                self._user32.TranslateMessage(ctypes.byref(msg))
                self._user32.DispatchMessageW(ctypes.byref(msg))
            self._poll_chords()
            time.sleep(0.02)
        self._drain_commands()

    def close(self) -> None:
        if self._stop.is_set():
            return
        self._stop.set()
        self._thread.join(timeout=1.0)
