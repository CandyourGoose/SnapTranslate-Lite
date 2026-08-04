import os
from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules
from PyInstaller.utils.hooks.tcl_tk import tcltk_info

import comtypes.client


# The bundled workspace Python ships Tcl/Tk correctly, but its library paths are
# not exported. PyInstaller's tkinter hook needs these paths during analysis.
python_base = Path(sys.base_prefix)
tcl_library = python_base / "tcl" / "tcl8.6"
tk_library = python_base / "tcl" / "tk8.6"
if tcl_library.is_dir() and tk_library.is_dir():
    os.environ["TCL_LIBRARY"] = str(tcl_library)
    os.environ["TK_LIBRARY"] = str(tk_library)
    # The portable build runtime cannot initialize Tcl during PyInstaller's
    # isolated availability probe, although its matching 8.6 DLLs and scripts
    # are present. Keep tkinter discoverable and package those scripts
    # explicitly instead of accepting the probe's false negative.
    tcltk_info.available = True
    tcltk_info.data_files = []

binaries = collect_dynamic_libs("onnxruntime")
comtypes.client.GetModule("UIAutomationCore.dll")
hiddenimports = [
    "tkinter",
    "comtypes.gen.UIAutomationClient",
    "comtypes.gen.stdole",
    *collect_submodules("pystray"),
]

a = Analysis(
    ["run_snaptranslate.py"],
    pathex=[],
    binaries=binaries,
    datas=[
        (str(tcl_library), "_tcl_data"),
        (str(tk_library), "_tk_data"),
        ("assets/models", "assets/models"),
        ("assets/app.ico", "assets"),
    ],
    hiddenimports=hiddenimports,
    excludes=[
        "cv2",
        "gtts",
        "openai",
        "paddle",
        "paddleocr",
        "paddlex",
        "pyttsx3",
        "pytesseract",
        "streamlit",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="SnapTranslate",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    icon="assets/app.ico",
    target_arch="x86_64",
)
