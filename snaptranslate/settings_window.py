from dataclasses import dataclass, replace
import tkinter as tk
from tkinter import ttk

from .domain import PopupContent, TranslationSource
from .hotkeys import format_hotkey, parse_hotkey
from .resource_path import resource_path
from .settings import Settings
from .windows_display import toplevel_dpi_scale


_ORDER = ("ctrl", "alt", "shift", "win", "tab")
_MODIFIER_KEYSYMS = {
    "Control_L": "ctrl",
    "Control_R": "ctrl",
    "Alt_L": "alt",
    "Alt_R": "alt",
    "Shift_L": "shift",
    "Shift_R": "shift",
    "Super_L": "win",
    "Super_R": "win",
    "Win_L": "win",
    "Win_R": "win",
    "Tab": "tab",
}

BORDER_SWATCHES = {
    "blue": "#60a5fa",
    "green": "#6ee7b7",
    "purple": "#c4b5fd",
    "rose": "#fda4af",
    "yellow": "#facc15",
    "none": None,
}
PANEL_SWATCHES = {
    "slate": "#223a58",
    "midnight": "#244936",
    "teal": "#4a3559",
    "forest": "#54332b",
    "plum": "#3d444d",
    "graphite": "#17191d",
}


@dataclass(frozen=True)
class SwatchStyle:
    fill: str
    outline: str
    diagonal: bool = False


@dataclass(frozen=True)
class StatusStyle:
    foreground: str
    bold: bool
    timeout_ms: int | None


def swatch_style(kind: str, preset: str) -> SwatchStyle:
    if kind == "border" and preset == "none":
        return SwatchStyle("#ffffff", "#111827", True)
    palette = BORDER_SWATCHES if kind == "border" else PANEL_SWATCHES
    color = palette[preset]
    if color is None:
        raise ValueError(f"无效色块：{kind}/{preset}")
    return SwatchStyle(color, "#cbd5e1")


def status_style(message: str) -> StatusStyle:
    if message == "设置保存成功":
        return StatusStyle("#3f8f66", True, 1000)
    return StatusStyle("#475569", False, None)


def compact_window_size(
    requested_width: int,
    requested_height: int,
    scale: float = 1.0,
) -> tuple[int, int]:
    scale = max(1.0, float(scale))
    return (
        max(round(380 * scale), requested_width + round(24 * scale)),
        requested_height + round(8 * scale),
    )


def compose_hotkey(modifiers: set[str], key: str) -> str:
    ordered = [name for name in _ORDER if name in modifiers]
    canonical = "+".join([*ordered, key.lower()])
    return parse_hotkey(canonical).canonical


class HotkeyCaptureModel:
    def __init__(self, values: dict[str, str]) -> None:
        self._values = {
            target: parse_hotkey(value).canonical for target, value in values.items()
        }
        self.active_target: str | None = None

    def begin(self, target: str) -> None:
        self.active_target = target

    def complete(self, value: str) -> None:
        if self.active_target is None:
            return
        self._values[self.active_target] = parse_hotkey(value).canonical
        self.active_target = None

    def cancel(self) -> None:
        self.active_target = None

    def set_value(self, target: str, value: str) -> None:
        self._values[target] = parse_hotkey(value).canonical

    def value(self, target: str) -> str:
        return self._values[target]

    def display(self, target: str) -> str:
        if self.active_target == target:
            return "请按组合键…"
        return format_hotkey(self._values[target])


class SettingsWindow:
    def __init__(
        self,
        root: tk.Tk,
        settings: Settings,
        on_save,
        on_close,
        key_recorder=None,
        on_capture=None,
        on_focus=None,
        on_realtime=None,
    ) -> None:
        self.root = root
        self._settings = settings
        self._on_save = on_save
        self._on_close = on_close
        self._key_recorder = key_recorder
        self._on_capture = on_capture or (lambda _active: None)
        self._on_focus = on_focus or (lambda _active: None)
        self._on_realtime = on_realtime or (lambda _enabled: None)
        self._focus_active = False
        self._capture_model = HotkeyCaptureModel(
            {
                "translate": settings.translate_hotkey,
                "realtime": settings.realtime_hotkey,
                "ocr": settings.ocr_hotkey,
            }
        )
        self._capture_buttons: dict[str, ttk.Button] = {}
        self._swatch_canvases: dict[tuple[str, str], tk.Canvas] = {}
        self._status_after_id: str | None = None
        self._realtime_status_after_id: str | None = None
        self._dpi_after_id: str | None = None
        self._layout_scale = 1.0
        try:
            self._base_tk_scaling = float(root.tk.call("tk", "scaling"))
        except (AttributeError, tk.TclError, TypeError, ValueError):
            self._base_tk_scaling = 96 / 72

        root.title("Snap Translate 设置")
        try:
            root.iconbitmap(str(resource_path("assets/app.ico")))
        except tk.TclError:
            pass
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.translate_hotkey = tk.StringVar(value=self._capture_model.display("translate"))
        self.realtime_hotkey = tk.StringVar(value=self._capture_model.display("realtime"))
        self.ocr_hotkey = tk.StringVar(value=self._capture_model.display("ocr"))
        self.realtime_enabled = tk.BooleanVar(value=settings.realtime_enabled)
        self.realtime_status = tk.StringVar(value="")
        self.translation_source = tk.StringVar(value=settings.translation_source.value)
        self.popup_seconds = tk.StringVar(value=str(settings.popup_seconds))
        self.popup_content = tk.StringVar(value=settings.popup_content.value)
        self.popup_border = tk.StringVar(value=settings.popup_border)
        self.popup_panel = tk.StringVar(value=settings.popup_panel)
        self.silent_start = tk.BooleanVar(value=settings.silent_start)
        self.status = tk.StringVar(value="关闭窗口后程序继续在托盘运行")

        self._frame = None
        self._build_content(1.0)

        root.bind("<Button-1>", self._root_click, add="+")
        root.bind("<FocusIn>", self._focus_in, add="+")
        root.bind("<FocusOut>", self._focus_out, add="+")
        root.bind_all("<Tab>", self._block_tab, add="+")
        self._resize_to_content(1.0, preserve_position=False)

    @staticmethod
    def _scaled_px(value: int, scale: float) -> int:
        return max(1, round(value * max(1.0, float(scale))))

    def _build_content(self, scale: float) -> None:
        if self._frame is not None:
            self._frame.destroy()
        self._layout_scale = max(1.0, float(scale))
        px = lambda value: self._scaled_px(value, self._layout_scale)
        self._capture_buttons.clear()
        self._swatch_canvases.clear()

        frame = ttk.Frame(self.root, padding=px(18))
        frame.pack(fill="both", expand=True)
        self._frame = frame

        hotkeys = ttk.LabelFrame(frame, text="快捷键", padding=px(8))
        hotkeys.pack(fill="x", pady=px(6))
        self._hotkey_row(hotkeys, "划词翻译", "translate", self.translate_hotkey)
        self._hotkey_row(
            hotkeys,
            "实时翻译",
            "realtime",
            self.realtime_hotkey,
            check_variable=self.realtime_enabled,
        )
        self._hotkey_row(hotkeys, "OCR 翻译", "ocr", self.ocr_hotkey)

        source = ttk.LabelFrame(frame, text="翻译源", padding=px(8))
        source.pack(fill="x", pady=px(6))
        ttk.Radiobutton(source, text="自动最优", value="auto", variable=self.translation_source).pack(side="left")
        ttk.Radiobutton(source, text="仅 MyMemory", value="mymemory", variable=self.translation_source).pack(side="left", padx=px(18))

        display = ttk.LabelFrame(frame, text="输出效果", padding=px(8))
        display.pack(fill="x", pady=px(6))
        ttk.Label(display, text="翻译内容").grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(display, text="原文 + 译文", value="both", variable=self.popup_content).grid(row=0, column=1, sticky="w", padx=(px(18), 0))
        ttk.Radiobutton(display, text="只显示译文", value="translation_only", variable=self.popup_content).grid(row=0, column=2, sticky="w", padx=(px(18), 0))
        ttk.Label(display, text="显示时间（秒）").grid(row=1, column=0, sticky="w", pady=(px(10), 0))
        ttk.Entry(display, textvariable=self.popup_seconds, width=9).grid(row=1, column=1, sticky="w", padx=(px(18), 0), pady=(px(10), 0))
        self._swatch_row(
            display,
            row=2,
            label="悬浮边框颜色",
            kind="border",
            variable=self.popup_border,
            presets=BORDER_SWATCHES,
        )
        self._swatch_row(
            display,
            row=3,
            label="悬浮背景颜色",
            kind="panel",
            variable=self.popup_panel,
            presets=PANEL_SWATCHES,
        )

        ttk.Checkbutton(frame, text="静默启动（下次启动直接进入托盘）", variable=self.silent_start).pack(anchor="w", pady=px(10))
        ttk.Button(frame, text="保存设置", command=self._save).pack(fill="x", pady=(px(4), px(8)))
        self._status_label = tk.Label(
            frame,
            textvariable=self.status,
            foreground="#475569",
            font=("Microsoft YaHei UI", 9),
            wraplength=px(440),
            justify="center",
        )
        self._status_label.pack(anchor="center")

    def _resize_to_content(self, scale: float, preserve_position: bool = True) -> None:
        self.root.update_idletasks()
        requested_width = self.root.winfo_reqwidth()
        requested_height = self.root.winfo_reqheight()
        width, height = compact_window_size(requested_width, requested_height, scale)
        suffix = ""
        if preserve_position:
            suffix = f"{self.root.winfo_rootx():+d}{self.root.winfo_rooty():+d}"
        self.root.geometry(f"{width}x{height}{suffix}")
        self.root.minsize(requested_width, requested_height)

    def _set_tk_scaling(self, scale: float) -> None:
        self.root.tk.call("tk", "scaling", self._base_tk_scaling * scale)
        try:
            names = self.root.tk.splitlist(self.root.tk.call("font", "names"))
            for name in names:
                size = self.root.tk.call("font", "actual", name, "-size")
                self.root.tk.call("font", "configure", name, "-size", size)
        except (AttributeError, tk.TclError):
            pass

    def _apply_dpi_scale(self, scale: float) -> None:
        scale = max(1.0, float(scale))
        if abs(scale - self._layout_scale) < 0.05:
            return
        self._cancel_capture()
        self._set_tk_scaling(scale)
        self._build_content(scale)
        self._resize_to_content(scale)

    def _schedule_dpi_watch(self) -> None:
        if self._dpi_after_id is None:
            self._dpi_after_id = self.root.after(200, self._poll_dpi)

    def _cancel_dpi_watch(self) -> None:
        identifier = getattr(self, "_dpi_after_id", None)
        self._dpi_after_id = None
        if identifier is not None:
            try:
                self.root.after_cancel(identifier)
            except (AttributeError, tk.TclError):
                pass

    def _poll_dpi(self) -> None:
        self._dpi_after_id = None
        try:
            visible = self.root.state() != "withdrawn"
        except (AttributeError, tk.TclError):
            visible = False
        if not visible:
            return
        scale = toplevel_dpi_scale(self.root, fallback=self._layout_scale)
        if abs(scale - self._layout_scale) >= 0.05:
            self._apply_dpi_scale(scale)
        self._schedule_dpi_watch()

    def _hotkey_row(
        self,
        parent,
        label: str,
        target: str,
        variable: tk.StringVar,
        check_variable: tk.BooleanVar | None = None,
    ) -> None:
        row = ttk.Frame(parent)
        px = lambda value: self._scaled_px(value, self._layout_scale)
        row.pack(fill="x", pady=px(5))
        ttk.Label(row, text=label).pack(side="left")
        if target == "realtime":
            tk.Label(
                row,
                textvariable=self.realtime_status,
                foreground="#3f8f66",
                font=("Microsoft YaHei UI", 9),
                anchor="center",
            ).pack(side="left", padx=(px(12), px(8)), expand=True)
        button = ttk.Button(
            row,
            textvariable=variable,
            command=lambda: self._begin_capture(target),
        )
        button.pack(side="right")
        self._capture_buttons[target] = button
        if check_variable is not None:
            ttk.Checkbutton(
                row,
                variable=check_variable,
                command=self._toggle_realtime,
            ).pack(side="right", padx=(0, px(10)))

    def _swatch_row(
        self,
        parent,
        row: int,
        label: str,
        kind: str,
        variable: tk.StringVar,
        presets,
    ) -> None:
        px = lambda value: self._scaled_px(value, self._layout_scale)
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=(px(10), 0))
        holder = ttk.Frame(parent)
        holder.grid(row=row, column=1, columnspan=2, sticky="w", padx=(px(18), 0), pady=(px(10), 0))
        for preset in presets:
            canvas = tk.Canvas(holder, width=px(26), height=px(26), highlightthickness=0)
            canvas.pack(side="left", padx=(0, px(7)))
            canvas.bind(
                "<Button-1>",
                lambda _event, selected=preset: self._select_swatch(
                    kind,
                    variable,
                    selected,
                ),
            )
            self._swatch_canvases[(kind, preset)] = canvas
        self._redraw_swatches(kind, variable)

    def _select_swatch(self, kind: str, variable: tk.StringVar, preset: str) -> None:
        variable.set(preset)
        self._redraw_swatches(kind, variable)

    def _redraw_swatches(self, kind: str, variable: tk.StringVar) -> None:
        px = lambda value: self._scaled_px(value, self._layout_scale)
        presets = BORDER_SWATCHES if kind == "border" else PANEL_SWATCHES
        for preset in presets:
            canvas = self._swatch_canvases[(kind, preset)]
            canvas.delete("all")
            selected = variable.get() == preset
            if selected:
                canvas.create_rectangle(px(1), px(1), px(25), px(25), outline="#2563eb", width=px(2))
            style = swatch_style(kind, preset)
            canvas.create_rectangle(
                px(4),
                px(4),
                px(22),
                px(22),
                fill=style.fill,
                outline=style.outline,
                width=px(1),
            )
            if style.diagonal:
                canvas.create_line(px(5), px(21), px(21), px(5), fill="#111827", width=px(1))

    def _begin_capture(self, target: str) -> None:
        self._cancel_capture()
        self._capture_model.begin(target)
        self._refresh_hotkey_displays()
        self._on_capture(True)
        if self._key_recorder is not None:
            self._key_recorder.start(self._capture_result)

    def _capture_result(self, value: str | None, error: str | None) -> None:
        if error is not None:
            self.set_status(error)
            return
        if value is None:
            return
        self._capture_model.complete(value)
        self._refresh_hotkey_displays()
        self._on_capture(False)

    def _cancel_capture(self) -> None:
        if self._capture_model.active_target is None:
            return
        self._capture_model.cancel()
        if self._key_recorder is not None:
            self._key_recorder.cancel()
        self._refresh_hotkey_displays()
        self._on_capture(False)

    def _refresh_hotkey_displays(self) -> None:
        self.translate_hotkey.set(self._capture_model.display("translate"))
        self.realtime_hotkey.set(self._capture_model.display("realtime"))
        self.ocr_hotkey.set(self._capture_model.display("ocr"))

    def _root_click(self, event) -> None:
        target = self._capture_model.active_target
        if target is not None and event.widget is not self._capture_buttons.get(target):
            self._cancel_capture()

    def _block_tab(self, _event) -> str | None:
        return "break" if self._capture_model.active_target is not None else None

    def _set_focus(self, active: bool) -> None:
        if self._focus_active == active:
            return
        self._focus_active = active
        self._on_focus(active)

    def _focus_in(self, _event=None) -> None:
        if self.root.state() == "withdrawn":
            return
        self._set_focus(True)

    def _focus_out(self, _event=None) -> None:
        self.root.after_idle(self._check_focus)

    def _check_focus(self) -> None:
        focused = self.root.focus_get()
        inside = focused is not None and str(focused).startswith(str(self.root))
        if not inside:
            self._cancel_capture()
            self._set_focus(False)

    def _toggle_realtime(self) -> None:
        requested = self.realtime_enabled.get()
        try:
            self._on_realtime(requested)
            self.show_realtime_status(requested)
        except Exception as exc:
            self.realtime_enabled.set(self._settings.realtime_enabled)
            self.set_status(str(exc))

    def show_realtime_status(self, enabled: bool) -> None:
        if self._realtime_status_after_id is not None:
            try:
                self.root.after_cancel(self._realtime_status_after_id)
            except tk.TclError:
                pass
        self.realtime_status.set(f"实时翻译已{'开启' if enabled else '关闭'}")
        self._realtime_status_after_id = self.root.after(
            1000,
            self._clear_realtime_status,
        )

    def _clear_realtime_status(self) -> None:
        self._realtime_status_after_id = None
        self.realtime_status.set("")

    def _save(self) -> None:
        try:
            seconds = float(self.popup_seconds.get())
            if not 0.5 <= seconds <= 60.0:
                raise ValueError("显示时间应为 0.5～60 秒")
            proposed = replace(
                self._settings,
                translate_hotkey=self._capture_model.value("translate"),
                realtime_hotkey=self._capture_model.value("realtime"),
                ocr_hotkey=self._capture_model.value("ocr"),
                realtime_enabled=self._settings.realtime_enabled,
                translation_source=TranslationSource(self.translation_source.get()),
                popup_seconds=seconds,
                popup_content=PopupContent(self.popup_content.get()),
                popup_border=self.popup_border.get(),
                popup_panel=self.popup_panel.get(),
                silent_start=self.silent_start.get(),
            )
            self._on_save(proposed)
            self._settings = proposed
        except (ValueError, RuntimeError) as exc:
            self.set_status(str(exc))

    def show(self) -> None:
        self.root.deiconify()
        if hasattr(self, "_layout_scale"):
            try:
                self.root.update_idletasks()
                self._cancel_dpi_watch()
                self._poll_dpi()
            except (AttributeError, tk.TclError):
                pass
        self.root.lift()
        self._set_focus(True)
        self.root.focus_force()

    def hide(self) -> None:
        try:
            self._cancel_dpi_watch()
            self._cancel_capture()
            self._set_focus(False)
        finally:
            self.root.withdraw()
            if hasattr(self, "_base_tk_scaling") and getattr(
                self,
                "_layout_scale",
                1.0,
            ) != 1.0:
                try:
                    self._set_tk_scaling(1.0)
                    self._build_content(1.0)
                except (AttributeError, tk.TclError):
                    pass

    def set_status(self, message: str) -> None:
        if self._status_after_id is not None:
            try:
                self.root.after_cancel(self._status_after_id)
            except tk.TclError:
                pass
            self._status_after_id = None
        style = status_style(message)
        font = ("Microsoft YaHei UI", 9, "bold") if style.bold else ("Microsoft YaHei UI", 9)
        self._status_label.configure(foreground=style.foreground, font=font)
        self.status.set(message)
        if style.timeout_ms is not None:
            self._status_after_id = self.root.after(
                style.timeout_ms,
                self._clear_status,
            )

    def _clear_status(self) -> None:
        self._status_after_id = None
        self.status.set("")

    def apply_settings(self, settings: Settings) -> None:
        self._settings = settings
        self._capture_model.set_value("translate", settings.translate_hotkey)
        self._capture_model.set_value("realtime", settings.realtime_hotkey)
        self._capture_model.set_value("ocr", settings.ocr_hotkey)
        self._refresh_hotkey_displays()
        self.realtime_enabled.set(settings.realtime_enabled)
        self.translation_source.set(settings.translation_source.value)
        self.popup_seconds.set(str(settings.popup_seconds))
        self.popup_content.set(settings.popup_content.value)
        self.popup_border.set(settings.popup_border)
        self.popup_panel.set(settings.popup_panel)
        self._redraw_swatches("border", self.popup_border)
        self._redraw_swatches("panel", self.popup_panel)
        self.silent_start.set(settings.silent_start)
