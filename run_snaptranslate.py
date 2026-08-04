from __future__ import annotations

from dataclasses import asdict
import argparse
import json
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="SnapTranslate")
    parser.add_argument("--diagnose", action="store_true")
    parser.add_argument("--diagnose-output", type=Path)
    arguments = parser.parse_args(argv)

    if arguments.diagnose:
        from snaptranslate.diagnostics import run_diagnostics

        report = run_diagnostics()
        payload = json.dumps(asdict(report), ensure_ascii=False)
        if arguments.diagnose_output is not None:
            arguments.diagnose_output.write_text(payload, encoding="utf-8")
        else:
            print(payload)
        return 0 if report.ok else 1

    from snaptranslate.windows_display import enable_per_monitor_dpi

    enable_per_monitor_dpi()

    from snaptranslate.app import build_default_app

    return build_default_app().run()


if __name__ == "__main__":
    raise SystemExit(main())
