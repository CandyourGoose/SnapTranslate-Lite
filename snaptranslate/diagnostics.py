from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import platform
import sys
from typing import Mapping

from .resource_path import model_path


@dataclass(frozen=True)
class DiagnosticReport:
    ok: bool
    platform: str
    python_bits: str
    models: tuple[str, ...]
    errors: tuple[str, ...]


def default_model_paths() -> dict[str, Path]:
    return {
        name: model_path(name)
        for name in (
            "PP-OCRv5_mobile_det.onnx",
            "PP-OCRv5_mobile_rec.onnx",
            "ppocrv5_dict.txt",
        )
    }


def run_diagnostics(
    model_paths: Mapping[str, Path] | None = None,
    require_valid_onnx: bool = True,
) -> DiagnosticReport:
    errors: list[str] = []
    found: list[str] = []
    paths = model_paths or default_model_paths()
    for name, path in paths.items():
        if not path.is_file():
            errors.append(f"missing model asset: {name}: {path}")
            continue
        found.append(name)
        if require_valid_onnx and path.suffix.lower() == ".onnx":
            try:
                import onnxruntime as ort

                ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
            except Exception as exc:
                errors.append(f"invalid model asset: {name}: {exc}")

    bits = platform.architecture()[0]
    if sys.platform != "win32":
        errors.append(f"unsupported platform: {sys.platform}")
    if bits != "64bit":
        errors.append(f"64-bit Windows is required, found: {bits}")
    return DiagnosticReport(
        ok=not errors,
        platform=sys.platform,
        python_bits=bits,
        models=tuple(found),
        errors=tuple(errors),
    )
