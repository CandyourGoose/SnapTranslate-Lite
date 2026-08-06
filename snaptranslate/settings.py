from dataclasses import asdict, dataclass, replace
import json
import os
from pathlib import Path
import time

from . import APP_VERSION
from .domain import PopupContent, TranslationSource


BORDER_PRESETS = ("blue", "green", "purple", "rose", "yellow", "none")
PANEL_PRESETS = ("slate", "midnight", "teal", "forest", "plum", "graphite")


@dataclass(frozen=True)
class Settings:
    version: str = APP_VERSION
    translate_hotkey: str = "ctrl+l"
    realtime_hotkey: str = "ctrl+alt+l"
    ocr_hotkey: str = "tab+q"
    realtime_enabled: bool = False
    translation_source: TranslationSource = TranslationSource.AUTO
    popup_seconds: float = 2.2
    popup_content: PopupContent = PopupContent.BOTH
    popup_border: str = "blue"
    popup_panel: str = "slate"
    silent_start: bool = False


@dataclass(frozen=True)
class LoadResult:
    settings: Settings
    warning: str | None = None


def default_settings_path() -> Path:
    return Path(os.environ["APPDATA"]) / "SnapTranslate" / "settings.json"


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_settings_path()

    @staticmethod
    def _decode(raw: dict) -> Settings:
        popup_border = str(raw.get("popup_border", "blue"))
        if popup_border not in BORDER_PRESETS:
            popup_border = "blue"
        popup_panel = str(raw.get("popup_panel", "slate"))
        if popup_panel not in PANEL_PRESETS:
            popup_panel = "slate"
        settings = Settings(
            version=APP_VERSION,
            translate_hotkey=str(raw.get("translate_hotkey", "ctrl+l")),
            realtime_hotkey=str(raw.get("realtime_hotkey", "ctrl+alt+l")),
            ocr_hotkey=str(raw.get("ocr_hotkey", "tab+q")),
            realtime_enabled=bool(raw.get("realtime_enabled", False)),
            translation_source=TranslationSource(raw.get("translation_source", "auto")),
            popup_seconds=float(raw.get("popup_seconds", 2.2)),
            popup_content=PopupContent(raw.get("popup_content", "both")),
            popup_border=popup_border,
            popup_panel=popup_panel,
            silent_start=bool(raw.get("silent_start", False)),
        )
        if not 0.5 <= settings.popup_seconds <= 60.0:
            settings = replace(settings, popup_seconds=2.2)
        return settings

    def _reset_defaults(self, warning: str | None = None) -> LoadResult:
        settings = Settings()
        try:
            self.save(settings)
        except OSError as exc:
            detail = f"默认设置写入失败：{exc}"
            warning = "；".join(part for part in (warning, detail) if part)
        return LoadResult(settings, warning)

    def load(self) -> LoadResult:
        if not self.path.exists():
            return self._reset_defaults()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise TypeError("设置根节点必须是对象")
            if raw.get("version") != APP_VERSION:
                return self._reset_defaults()
            return LoadResult(self._decode(raw))
        except (OSError, ValueError, TypeError, KeyError) as exc:
            return self._reset_defaults(f"设置文件无效，已恢复默认值：{exc}")

    def save(self, settings: Settings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(settings)
        payload["translation_source"] = settings.translation_source.value
        payload["popup_content"] = settings.popup_content.value
        temp = self.path.with_suffix(".json.tmp")
        temp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        for attempt in range(5):
            try:
                os.replace(temp, self.path)
                return
            except OSError:
                if attempt == 4:
                    raise
                time.sleep(0.01 * (attempt + 1))
