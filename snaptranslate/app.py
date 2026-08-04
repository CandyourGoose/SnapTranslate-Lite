import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from queue import Empty, Queue
from types import SimpleNamespace

from .domain import TranslationFailure, UserInputError, validate_text
from .settings import Settings


class TkDispatcher:
    def __init__(self, root, on_error=None) -> None:
        self._root = root
        self._on_error = on_error or (lambda _exc: None)
        self._queue: Queue = Queue()
        self._closed = False
        self._root.after(20, self._drain)

    def call(self, function) -> None:
        if not self._closed:
            self._queue.put(function)

    def _drain(self) -> None:
        if self._closed:
            return
        try:
            while True:
                try:
                    function = self._queue.get_nowait()
                except Empty:
                    break
                try:
                    function()
                except Exception as exc:
                    try:
                        self._on_error(exc)
                    except Exception:
                        pass
        finally:
            if not self._closed:
                try:
                    self._root.after(20, self._drain)
                except Exception:
                    self._closed = True

    def close(self) -> None:
        self._closed = True


class SnapTranslateApp:
    def __init__(self, deps) -> None:
        self.deps = deps
        self._settings = Settings()
        self._settings_lock = threading.RLock()
        self._request_lock = threading.Lock()
        self._latest_request = 0
        self._realtime_notice_lock = threading.Lock()
        self._realtime_notice_generation = 0
        self._translation_futures = set()
        self._translation_futures_lock = threading.RLock()
        self._ocr_busy = threading.Lock()
        self._started = False
        self._closed = False

    @property
    def settings(self) -> Settings:
        with self._settings_lock:
            return self._settings

    def start(self) -> bool:
        if not self.deps.instance.acquire():
            self.deps.instance.signal_existing()
            return False
        loaded = self.deps.store.load()
        with self._settings_lock:
            self._settings = loaded.settings
        apply_settings = getattr(self.deps.window, "apply_settings", None)
        if apply_settings is not None:
            apply_settings(loaded.settings)
        startup_warning = loaded.warning
        try:
            self.deps.hotkeys.replace(
                {
                    "translate": loaded.settings.translate_hotkey,
                    "realtime": loaded.settings.realtime_hotkey,
                    "ocr": loaded.settings.ocr_hotkey,
                }
            )
        except RuntimeError as exc:
            startup_warning = "；".join(part for part in (startup_warning, str(exc)) if part)
        self.deps.instance.wait_for_wake(self.on_instance_wake)
        self.deps.tray.start()
        fullscreen = getattr(self.deps, "fullscreen", None)
        if fullscreen is not None:
            fullscreen.start()
        realtime = getattr(self.deps, "realtime", None)
        if realtime is not None:
            realtime.set_enabled(loaded.settings.realtime_enabled)
            realtime.start()
        self._started = True
        if startup_warning:
            self.deps.window.set_status(startup_warning)
        if not loaded.settings.silent_start:
            self.show_settings()
        return True

    def show_settings(self) -> None:
        self.deps.window.show()

    def hide_settings(self) -> None:
        self.deps.window.hide()
        self.set_input_pause("recording", False)
        self.set_input_pause("settings", False)

    def on_instance_wake(self) -> None:
        self.deps.dispatcher.call(self.show_settings)

    def _next_request_id(self) -> int:
        with self._request_lock:
            self._latest_request += 1
            return self._latest_request

    def _is_current_request(self, request_id: int) -> bool:
        with self._request_lock:
            return request_id == self._latest_request

    def _show_message(
        self,
        message: str,
        request_id: int | None = None,
        neutral: bool = False,
    ) -> None:
        settings = self.settings

        def show() -> None:
            if request_id is not None and not self._is_current_request(request_id):
                return
            self.deps.popup.show_message(
                message,
                settings,
                request_id=request_id,
                neutral=neutral,
            )

        self.deps.dispatcher.call(show)

    def set_input_pause(self, reason: str, active: bool) -> None:
        realtime = getattr(self.deps, "realtime", None)
        try:
            self.deps.hotkeys.set_paused(reason, active)
        finally:
            if realtime is not None:
                realtime.set_paused(reason, active)

    def set_realtime_enabled(self, enabled: bool, notify_popup: bool = True) -> None:
        previous = self.settings
        if previous.realtime_enabled == enabled:
            return
        proposed = replace(previous, realtime_enabled=enabled)
        self.deps.store.save(proposed)
        with self._settings_lock:
            self._settings = proposed
        realtime = getattr(self.deps, "realtime", None)
        if realtime is not None:
            realtime.set_enabled(enabled)
        self.deps.window.apply_settings(proposed)
        if notify_popup:
            self._show_realtime_notice(enabled)

    def _show_realtime_notice(self, enabled: bool) -> None:
        with self._realtime_notice_lock:
            self._realtime_notice_generation += 1
            generation = self._realtime_notice_generation
        settings = self.settings
        message = f"实时翻译已{'开启' if enabled else '关闭'}"
        self.deps.popup.dismiss()

        def show() -> None:
            with self._realtime_notice_lock:
                if generation != self._realtime_notice_generation:
                    return
            self.deps.popup.show_message(message, settings)

        self.deps.dispatcher.call(show)

    def toggle_realtime(self) -> None:
        self.set_realtime_enabled(not self.settings.realtime_enabled)

    def handle_pointer_down(self, point: tuple[int, int]) -> None:
        def dismiss_if_outside() -> None:
            if not self.deps.popup.contains_point(point):
                self.deps.popup.dismiss()

        self.deps.dispatcher.call(dismiss_if_outside)

    def _submit_translation(self, text_provider) -> None:
        request_id = self._next_request_id()

        def job() -> None:
            try:
                original = validate_text(text_provider())
                settings = self.settings
                translated = self.deps.translator.translate(
                    original,
                    settings.translation_source,
                )
                def show_result() -> None:
                    if not self._is_current_request(request_id):
                        return
                    self.deps.popup.show(
                        original,
                        translated.text,
                        settings,
                        request_id=request_id,
                    )

                self.deps.dispatcher.call(show_result)
            except (UserInputError, TranslationFailure) as exc:
                self._show_message(str(exc), request_id=request_id)
            except Exception as exc:
                self._show_message(f"翻译失败：{exc}", request_id=request_id)

        with self._translation_futures_lock:
            for future in tuple(self._translation_futures):
                if future.done():
                    self._translation_futures.discard(future)
                elif not future.running():
                    future.cancel()
            future = self.deps.background.submit(job)
            if hasattr(future, "add_done_callback"):
                self._translation_futures.add(future)
                future.add_done_callback(self._forget_translation_future)

    def _forget_translation_future(self, future) -> None:
        with self._translation_futures_lock:
            self._translation_futures.discard(future)

    def translate_text(self, text: str) -> None:
        self._submit_translation(lambda: text)

    def translate_selection(self) -> None:
        self._submit_translation(self.deps.selection.capture)

    def translate_screenshot(self) -> None:
        self.deps.screenshot.capture(
            self._accept_screenshot,
            on_state=lambda active: self.set_input_pause("ocr_overlay", active),
        )

    def _accept_screenshot(self, image) -> None:
        if not self._ocr_busy.acquire(blocking=False):
            self._show_message("OCR 正在处理中")
            return

        request_id = self._next_request_id()

        def job() -> None:
            try:
                original = validate_text(self.deps.ocr.recognize(image).text)
                settings = self.settings
                translated = self.deps.translator.translate(
                    original,
                    settings.translation_source,
                )
                def show_result() -> None:
                    if not self._is_current_request(request_id):
                        return
                    self.deps.popup.show(
                        original,
                        translated.text,
                        settings,
                        request_id=request_id,
                    )

                self.deps.dispatcher.call(show_result)
            except (UserInputError, TranslationFailure) as exc:
                message = str(exc)

                def show_known_error(message=message) -> None:
                    if not self._is_current_request(request_id):
                        return
                    self.deps.popup.show_message(
                        message,
                        self.settings,
                        request_id=request_id,
                        neutral=message == "未识别到文字",
                    )

                self.deps.dispatcher.call(show_known_error)
            except Exception as exc:
                message = f"OCR 失败：{exc}"

                def show_unexpected_error(message=message) -> None:
                    if not self._is_current_request(request_id):
                        return
                    self.deps.popup.show_message(
                        message,
                        self.settings,
                        request_id=request_id,
                    )

                self.deps.dispatcher.call(show_unexpected_error)
            finally:
                self._ocr_busy.release()

        self.deps.background.submit(job)

    def save_settings(self, proposed: Settings) -> None:
        previous = self.settings
        proposed_bindings = {
            "translate": proposed.translate_hotkey,
            "realtime": proposed.realtime_hotkey,
            "ocr": proposed.ocr_hotkey,
        }
        self.deps.hotkeys.replace(proposed_bindings)
        try:
            self.deps.store.save(proposed)
        except Exception:
            self.deps.hotkeys.replace(
                {
                    "translate": previous.translate_hotkey,
                    "realtime": previous.realtime_hotkey,
                    "ocr": previous.ocr_hotkey,
                }
            )
            raise
        with self._settings_lock:
            self._settings = proposed
        self.deps.window.set_status("设置保存成功")

    def run(self) -> int:
        if not self.start():
            self.shutdown()
            return 0
        run_loop = getattr(self.deps, "run_loop", None)
        if run_loop is not None:
            run_loop()
        return 0

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        fullscreen = getattr(self.deps, "fullscreen", None)
        if fullscreen is not None:
            fullscreen.close()
        realtime = getattr(self.deps, "realtime", None)
        if realtime is not None:
            realtime.close()
        self.deps.hotkeys.close()
        key_recorder = getattr(self.deps, "key_recorder", None)
        if key_recorder is not None:
            key_recorder.close()
        close_popup = getattr(self.deps.popup, "close", None)
        if close_popup is not None:
            close_popup()
        self.deps.ocr.close()
        self.deps.translator.close()
        self.deps.background.shutdown(wait=False, cancel_futures=True)
        self.deps.tray.stop()
        self.deps.instance.close()
        self.deps.destroy()


def build_default_app() -> SnapTranslateApp:
    import tkinter as tk

    from .fullscreen import ExclusiveFullscreenMonitor
    from .hotkeys import HotkeyManager, WinHotkeyApi
    from .key_recorder import PhysicalKeyRecorder
    from .ocr.service import OcrService
    from .popup import PopupPresenter
    from .realtime import RealtimeController
    from .screenshot import ScreenshotOverlay
    from .selection import SelectionCapture
    from .settings import SettingsStore
    from .settings_window import SettingsWindow
    from .single_instance import SingleInstance
    from .translator import Translator
    from .tray import TrayController

    root = tk.Tk()
    root.withdraw()
    dispatcher = TkDispatcher(root)
    app_holder: dict[str, SnapTranslateApp] = {}

    def app_call(method_name: str, *args) -> None:
        app = app_holder.get("app")
        if app is not None:
            getattr(app, method_name)(*args)

    hotkey_api = WinHotkeyApi()
    hotkeys = HotkeyManager(
        hotkey_api,
        on_action=lambda action: dispatcher.call(
            lambda: app_call(
                {
                    "translate": "translate_selection",
                    "realtime": "toggle_realtime",
                    "ocr": "translate_screenshot",
                }[action]
            )
        ),
    )
    hotkey_api.set_callback(hotkeys.trigger)
    key_recorder = PhysicalKeyRecorder(dispatch=dispatcher.call)

    selection = SelectionCapture()
    popup = PopupPresenter(root)
    realtime = RealtimeController(
        capture=selection,
        on_text=lambda text: app_call("translate_text", text),
        on_pointer_down=lambda point: app_call("handle_pointer_down", point),
    )

    window = SettingsWindow(
        root,
        Settings(),
        on_save=lambda proposed: app_holder["app"].save_settings(proposed),
        on_close=lambda: app_call("hide_settings"),
        key_recorder=key_recorder,
        on_capture=lambda active: app_call("set_input_pause", "recording", active),
        on_focus=lambda active: app_call("set_input_pause", "settings", active),
        on_realtime=lambda enabled: app_call("set_realtime_enabled", enabled, False),
    )
    tray = TrayController(
        on_open=lambda: dispatcher.call(lambda: app_call("show_settings")),
        on_exit=lambda: dispatcher.call(lambda: app_call("shutdown")),
    )
    background = ThreadPoolExecutor(max_workers=2, thread_name_prefix="snaptranslate")
    fullscreen = ExclusiveFullscreenMonitor(
        on_change=lambda active: dispatcher.call(
            lambda: app_call("set_input_pause", "fullscreen", active)
        )
    )

    def destroy() -> None:
        dispatcher.close()
        root.destroy()

    deps = SimpleNamespace(
        store=SettingsStore(),
        instance=SingleInstance(),
        window=window,
        tray=tray,
        dispatcher=dispatcher,
        scheduler=root,
        background=background,
        selection=selection,
        realtime=realtime,
        screenshot=ScreenshotOverlay(root),
        translator=Translator(),
        popup=popup,
        hotkeys=hotkeys,
        key_recorder=key_recorder,
        fullscreen=fullscreen,
        ocr=OcrService(),
        run_loop=root.mainloop,
        destroy=destroy,
    )
    app = SnapTranslateApp(deps)
    app_holder["app"] = app
    return app
