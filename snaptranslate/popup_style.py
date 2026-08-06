from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFilter


@dataclass(frozen=True)
class PopupMetrics:
    original_font: int
    translation_font: int
    padding_x: int
    padding_top: int
    padding_bottom: int
    line_gap: int
    text_width: int
    minimum_width: int
    maximum_width: int
    minimum_height: int
    border_width: int
    corner_radius: int
    cursor_offset: tuple[int, int]


def popup_metrics(physical_scale: float, font_scale: float) -> PopupMetrics:
    physical_scale = max(1.0, float(physical_scale))
    font_scale = max(0.25, float(font_scale))

    def px(value: int) -> int:
        return max(1, round(value * physical_scale))

    def font(value: int) -> int:
        return max(1, round(value * font_scale))

    return PopupMetrics(
        original_font=font(10),
        translation_font=font(11),
        padding_x=px(14),
        padding_top=px(10),
        padding_bottom=px(10),
        line_gap=px(6),
        text_width=px(520),
        minimum_width=px(120),
        maximum_width=px(548),
        minimum_height=px(40),
        border_width=px(1),
        corner_radius=px(8),
        cursor_offset=(px(16), px(20)),
    )


def _hex_rgb(color: str) -> tuple[int, int, int]:
    return tuple(int(color[index:index + 2], 16) for index in (1, 3, 5))


def build_panel_background(
    width: int,
    height: int,
    colors: tuple[str, str],
    corner_radius: int | None = None,
) -> Image.Image:
    width, height = max(1, width), max(1, height)
    base = Image.new("RGBA", (width, height), (*_hex_rgb(colors[1]), 255))
    mist = Image.new("RGBA", base.size, (0, 0, 0, 0))
    mist_draw = ImageDraw.Draw(mist)
    mist_draw.ellipse(
        (-width // 4, -round(height * 1.10), width * 5 // 4, round(height * 0.45)),
        fill=(*_hex_rgb(colors[0]), 70),
    )
    mist = mist.filter(
        ImageFilter.GaussianBlur(max(8, round(min(width, height) * 0.22)))
    )
    shade = Image.new("RGBA", base.size, (0, 0, 0, 0))
    shade_draw = ImageDraw.Draw(shade)
    shade_draw.ellipse(
        (-width // 10, round(height * 0.55), width * 11 // 10, round(height * 1.90)),
        fill=(0, 0, 0, 45),
    )
    shade = shade.filter(
        ImageFilter.GaussianBlur(max(8, round(min(width, height) * 0.30)))
    )
    result = Image.alpha_composite(Image.alpha_composite(base, mist), shade)
    if corner_radius is None:
        return result.convert("RGB")
    mask = Image.new("L", result.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, width - 1, height - 1),
        radius=max(1, int(corner_radius)),
        fill=255,
    )
    result.putalpha(mask)
    return result
