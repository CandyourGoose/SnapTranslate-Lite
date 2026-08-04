from __future__ import annotations

import tkinter as tk
from typing import Callable

from PIL import Image, ImageGrab

from .windows_display import (
    Rect,
    cursor_position,
    monitor_rect_from_point,
    place_toplevel_physical,
    toplevel_dpi_scale,
)


MIN_DRAG_SIZE = 5


def normalize_drag(start: tuple[int, int], end: tuple[int, int]) -> Rect | None:
    left, right = sorted((start[0], end[0]))
    top, bottom = sorted((start[1], end[1]))
    rect = Rect(left, top, right, bottom)
    if rect.width < MIN_DRAG_SIZE or rect.height < MIN_DRAG_SIZE:
        return None
    return rect


def globalize_rect(local: Rect, screen: Rect) -> Rect:
    return Rect(
        local.left + screen.left,
        local.top + screen.top,
        local.right + screen.left,
        local.bottom + screen.top,
    )


def clamp_point(
    point: tuple[int, int],
    width: int,
    height: int,
) -> tuple[int, int]:
    return (
        max(0, min(point[0], width)),
        max(0, min(point[1], height)),
    )


class ScreenshotOverlay:
    def __init__(self, root: tk.Misc, screen_provider=None) -> None:
        self._root = root
        self._window: tk.Toplevel | None = None
        self._screen_provider = screen_provider or (
            lambda: monitor_rect_from_point(cursor_position())
        )

    def capture(
        self,
        callback: Callable[[Image.Image], None],
        on_state: Callable[[bool], None] | None = None,
    ) -> None:
        if self._window is not None and self._window.winfo_exists():
            self._window.lift()
            return

        state_callback = on_state or (lambda _active: None)
        window = None
        state_active = False
        start: tuple[int, int] | None = None
        selection_id: int | None = None
        outline_width = 2
        cleaned = False

        def cleanup() -> None:
            nonlocal cleaned, state_active
            if cleaned:
                return
            cleaned = True
            self._window = None
            if window is not None:
                try:
                    window.grab_release()
                except Exception:
                    pass
                try:
                    if window.winfo_exists():
                        window.destroy()
                except Exception:
                    pass
            if state_active:
                state_active = False
                try:
                    state_callback(False)
                except Exception:
                    pass

        def cancel(_event=None) -> None:
            cleanup()

        try:
            screen = self._screen_provider()
            window = tk.Toplevel(self._root)
            window.withdraw()
            self._window = window
            state_active = True
            state_callback(True)
            window.overrideredirect(True)
            window.attributes("-topmost", True)
            window.attributes("-alpha", 0.0)
            window.geometry(
                f"{screen.width}x{screen.height}{screen.left:+d}{screen.top:+d}"
            )
            window.configure(cursor="crosshair")

            canvas = tk.Canvas(
                window,
                bg="#0f172a",
                highlightthickness=0,
                cursor="crosshair",
            )
            canvas.pack(fill="both", expand=True)

            def press(event) -> None:
                nonlocal start, selection_id
                point = clamp_point((event.x, event.y), screen.width, screen.height)
                start = point
                selection_id = canvas.create_rectangle(
                    point[0],
                    point[1],
                    point[0],
                    point[1],
                    outline="#38bdf8",
                    width=outline_width,
                    fill="#e0f2fe",
                )

            def drag(event) -> None:
                if start is not None and selection_id is not None:
                    point = clamp_point((event.x, event.y), screen.width, screen.height)
                    canvas.coords(
                        selection_id,
                        start[0],
                        start[1],
                        point[0],
                        point[1],
                    )

            def release(event) -> None:
                if start is None:
                    return
                end = clamp_point((event.x, event.y), screen.width, screen.height)
                local_rect = normalize_drag(start, end)
                if local_rect is None:
                    cancel()
                    return
                global_rect = globalize_rect(local_rect, screen)
                window.withdraw()

                def grab() -> None:
                    try:
                        image = ImageGrab.grab(
                            bbox=(
                                global_rect.left,
                                global_rect.top,
                                global_rect.right,
                                global_rect.bottom,
                            ),
                            all_screens=True,
                        )
                    except Exception:
                        cleanup()
                        return
                    cleanup()
                    callback(image)

                window.after(30, grab)

            window.bind("<Escape>", cancel)
            canvas.bind("<ButtonPress-1>", press)
            canvas.bind("<B1-Motion>", drag)
            canvas.bind("<ButtonRelease-1>", release)
            window.deiconify()
            window.update_idletasks()
            window.update()
            if not place_toplevel_physical(window, screen):
                cleanup()
                return
            scale = toplevel_dpi_scale(window)
            outline_width = max(2, round(2 * scale))
            if selection_id is not None:
                canvas.itemconfigure(selection_id, width=outline_width)
            window.attributes("-alpha", 0.35)
            window.focus_force()
            window.grab_set()
        except Exception:
            cleanup()
