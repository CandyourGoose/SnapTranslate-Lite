from pathlib import Path
import sys


def resource_path(relative: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return base / relative


def model_path(name: str) -> Path:
    return resource_path(f"assets/models/{name}")

