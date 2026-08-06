from __future__ import annotations

import tkinter as tk

from PIL import ImageTk

from .domain import PopupContent
from .popup_style import build_panel_background, popup_metrics
from .settings import Settings
from .windows_display import (
    MonitorSnapshot,
    Rect,
    apply_toplevel_rounding,
    cursor_position,
    monitor_snapshot_from_point,
    place_toplevel_physical,
    toplevel_dpi_scale,
)


FLOAT_FG = "#f1f5f9"
FLOAT_MUTED = "#a8b3c4"
BORDER_COLORS = {
    "blue": "#60a5fa",
    "green": "#6ee7b7",
    "purple": "#c4b5fd",
    "rose": "#fda4af",
    "yellow": "#facc15",
    "none": None,
}
PANEL_GRADIENTS = {
    "slate": ("#4a7ec4", "#101722"),
    "midnight": ("#439168", "#111b17"),
    "teal": ("#8b5eac", "#191521"),
    "forest": ("#a45b46", "#201613"),
    "plum": ("#848f9d", "#1b1d20"),
    "graphite": ("#636f80", "#0e0f11"),
}


def build_popup_lines(
    original: str,
    translated: str,
    mode: PopupContent,
) -> tuple[str, ...]:
    return (translated,) if mode is PopupContent.TRANSLATION_ONLY else (original, translated)


def clamp_position(
    x: int,
    y: int,
    width: int,
    height: int,
    work_area: tuple[int, int, int, int],
) -> tuple[int, int]:
    left, top, right, bottom = work_area
    return max(left, min(x, right - width)), max(top, min(y, bottom - height))


def border_color(preset: str) -> str | None:
    return BORDER_COLORS.get(preset, BORDER_COLORS["blue"])


def panel_gradient(preset: str) -> tuple[str, str]:
    return PANEL_GRADIENTS.get(preset, PANEL_GRADIENTS["slate"])


def tk_reference_scale(root) -> float:
    try:
        return max(0.25, float(root.winfo_fpixels("1i")) / 96.0)
    except (AttributeError, tk.TclError, TypeError, ValueError):
        return 1.0


def _tk_fallback_snapshot(root) -> MonitorSnapshot:
    try:
        left = int(root.winfo_vrootx())
        top = int(root.winfo_vrooty())
        width = int(root.winfo_vrootwidth())
        height = int(root.winfo_vrootheight())
    except Exception:
        left = 0
        top = 0
        try:
            width = int(root.winfo_screenwidth())
            height = int(root.winfo_screenheight())
        except Exception:
            width, height = 800, 600
    width = max(1, width)
    height = max(1, height)
    bounds = Rect(left, top, left + width, top + height)
    return MonitorSnapshot(bounds=bounds, work_area=bounds, dpi=96)


def _cursor_and_snapshot(root) -> tuple[tuple[int, int], MonitorSnapshot]:
    try:
        cursor = cursor_position()
    except Exception:
        try:
            pointer = root.winfo_pointerxy()
            cursor = int(pointer[0]), int(pointer[1])
        except Exception:
            cursor = (0, 0)
    try:
        snapshot = monitor_snapshot_from_point(cursor)
    except Exception:
        snapshot = _tk_fallback_snapshot(root)
    return cursor, snapshot


class PopupRequestGate:
    def __init__(self) -> None:
        self._latest = 0

    def accept(self, request_id: int | None) -> bool:
        if request_id is None:
            return True
        if request_id < self._latest:
            return False
        self._latest = request_id
        return True


class PopupLifecycle:
    def __init__(self, root) -> None:
        self._root = root
        self.window = None
        self._timer = None

    def replace(self, window) -> None:
        self.dismiss()
        self.window = window

    def set_timer(self, timer) -> None:
        if self._timer is not None:
            self._root.after_cancel(self._timer)
        self._timer = timer

    def dismiss(self) -> None:
        if self._timer is not None:
            try:
                self._root.after_cancel(self._timer)
            except tk.TclError:
                pass
            self._timer = None
        window = self.window
        self.window = None
        if window is not None and window.winfo_exists():
            window.destroy()

    def contains_point(self, point: tuple[int, int]) -> bool:
        window = self.window
        if window is None or not window.winfo_exists():
            return False
        left = window.winfo_rootx()
        top = window.winfo_rooty()
        return (
            left <= point[0] < left + window.winfo_width()
            and top <= point[1] < top + window.winfo_height()
        )


class PopupPresenter:
    def __init__(self, root: tk.Misc) -> None:
        self._root = root
        self._lifecycle = PopupLifecycle(root)
        self._requests = PopupRequestGate()

    def show(
        self,
        original: str,
        translated: str,
        settings: Settings,
        request_id: int | None = None,
        neutral: bool = False,
    ) -> None:
        if not self._requests.accept(request_id):
            return

        (cursor_x, cursor_y), snapshot = _cursor_and_snapshot(self._root)
        window = tk.Toplevel(self._root)
        window.withdraw()
        window.overrideredirect(True)
        window.attributes("-topmost", True)
        window.attributes("-alpha", 0.0)
        self._lifecycle.replace(window)

        gradient = panel_gradient(settings.popup_panel)
        outline = border_color(settings.popup_border)
        window.configure(bg=outline or gradient[0])
        target = snapshot.bounds
        seed_x = max(target.left, min(cursor_x, target.right - 1))
        seed_y = max(target.top, min(cursor_y, target.bottom - 1))
        window.geometry(f"1x1{seed_x:+d}{seed_y:+d}")
        window.deiconify()
        window.update_idletasks()
        window.update()
        target_scale = toplevel_dpi_scale(window, fallback=snapshot.scale)
        metrics = popup_metrics(
            physical_scale=target_scale,
            font_scale=target_scale / tk_reference_scale(self._root),
        )

        outer = tk.Frame(
            window,
            bg=outline or gradient[0],
            padx=metrics.border_width if outline else 0,
            pady=metrics.border_width if outline else 0,
        )
        outer.pack(fill="both", expand=True)
        canvas = tk.Canvas(
            outer,
            bg=outline or gradient[0],
            highlightthickness=0,
            borderwidth=0,
        )
        canvas.pack(fill="both", expand=True)

        lines = build_popup_lines(original, translated, settings.popup_content)
        text_items = []
        y = metrics.padding_top
        maximum_right = 0
        for index, line in enumerate(lines):
            is_original = len(lines) == 2 and index == 0
            font_size = (
                metrics.original_font
                if is_original or neutral
                else metrics.translation_font
            )
            foreground = FLOAT_MUTED if is_original or neutral else FLOAT_FG
            item = canvas.create_text(
                metrics.padding_x,
                y,
                text=line,
                fill=foreground,
                anchor="nw",
                justify="left",
                width=metrics.text_width,
                font=("Microsoft YaHei UI", font_size),
                tags=("text",),
            )
            canvas.update_idletasks()
            bounds = canvas.bbox(item) or (
                metrics.padding_x,
                y,
                metrics.padding_x,
                y + metrics.translation_font * 2,
            )
            text_items.append(item)
            maximum_right = max(maximum_right, bounds[2])
            y = bounds[3] + (
                metrics.line_gap
                if index + 1 < len(lines)
                else metrics.padding_bottom
            )

        width = max(
            metrics.minimum_width,
            min(metrics.maximum_width, maximum_right + metrics.padding_x),
        )
        height = max(metrics.minimum_height, y)
        canvas.configure(width=width, height=height)
        inner_radius = (
            max(1, metrics.corner_radius - metrics.border_width)
            if outline
            else None
        )
        background = ImageTk.PhotoImage(
            build_panel_background(
                width,
                height,
                gradient,
                corner_radius=inner_radius,
            )
        )
        canvas.create_image(0, 0, anchor="nw", image=background)
        canvas._background_image = background
        for item in text_items:
            canvas.tag_raise(item)

        window.update_idletasks()
        work_area = snapshot.work_area
        requested_width = window.winfo_reqwidth()
        requested_height = window.winfo_reqheight()
        x, y_position = clamp_position(
            cursor_x + metrics.cursor_offset[0],
            cursor_y + metrics.cursor_offset[1],
            requested_width,
            requested_height,
            (work_area.left, work_area.top, work_area.right, work_area.bottom),
        )
        window.geometry(
            f"{requested_width}x{requested_height}{x:+d}{y_position:+d}"
        )
        window.update_idletasks()
        window.update()
        final_rect = Rect(
            x,
            y_position,
            x + requested_width,
            y_position + requested_height,
        )
        place_toplevel_physical(window, final_rect)
        apply_toplevel_rounding(
            window,
            final_rect.width,
            final_rect.height,
            metrics.corner_radius,
        )
        window.attributes("-alpha", 0.96)
        timer = window.after(
            max(1, int(settings.popup_seconds * 1000)),
            self.dismiss,
        )
        self._lifecycle.set_timer(timer)

    def show_message(
        self,
        message: str,
        settings: Settings,
        request_id: int | None = None,
        neutral: bool = False,
    ) -> None:
        message_settings = Settings(
            **{
                **settings.__dict__,
                "popup_content": PopupContent.TRANSLATION_ONLY,
            }
        )
        self.show(
            "",
            message,
            message_settings,
            request_id=request_id,
            neutral=neutral,
        )

    def dismiss(self) -> None:
        self._lifecycle.dismiss()

    def contains_point(self, point: tuple[int, int]) -> bool:
        return self._lifecycle.contains_point(point)

    def close(self) -> None:
        self.dismiss()
