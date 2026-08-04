from PIL import Image, ImageDraw
import pystray

from .resource_path import resource_path


def make_tray_image() -> Image.Image:
    icon_path = resource_path("assets/app.ico")
    if icon_path.is_file():
        with Image.open(icon_path) as icon:
            return icon.convert("RGBA").resize((64, 64), Image.Resampling.LANCZOS)

    image = Image.new("RGBA", (64, 64), (30, 41, 59, 255))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((8, 8, 56, 56), radius=10, fill=(79, 70, 229, 255))
    draw.text((26, 24), "S", fill="white", stroke_width=1)
    return image


class TrayController:
    def __init__(self, on_open, on_exit) -> None:
        self._on_open = on_open
        self._on_exit = on_exit
        self._icon = pystray.Icon(
            "SnapTranslate",
            make_tray_image(),
            "SnapTranslate",
            menu=pystray.Menu(
                pystray.MenuItem("打开设置", self._open, default=True),
                pystray.MenuItem("退出", self._exit),
            ),
        )

    def _open(self, _icon=None, _item=None) -> None:
        self._on_open()

    def _exit(self, _icon=None, _item=None) -> None:
        self._on_exit()

    def start(self) -> None:
        self._icon.run_detached()

    def stop(self) -> None:
        self._icon.stop()
