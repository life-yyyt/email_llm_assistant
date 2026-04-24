# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build file for EmailLLMAssistant.

The packaged app is optimized for the Ollama workflow. Large local
Transformers/Torch model dependencies are intentionally excluded so the
desktop demo remains small and fast to build.
"""

import os
import sys


ROOT = os.path.dirname(os.path.abspath(SPEC))
CONDA_BIN = os.path.join(sys.base_prefix, "Library", "bin")


def _collect_runtime_binaries():
    """Collect the Conda/PyQt5 runtime DLLs needed by the GUI app."""
    names = [
        "Qt5Core_conda.dll",
        "Qt5Gui_conda.dll",
        "Qt5Widgets_conda.dll",
        "Qt5Network_conda.dll",
        "Qt5Svg_conda.dll",
        "Qt5DBus_conda.dll",
        "Qt5PrintSupport_conda.dll",
        "libjpeg.dll",
        "libpng16.dll",
        "libcrypto-3-x64.dll",
        "libssl-3-x64.dll",
        "libbz2.dll",
        "ffi.dll",
        "zstd.dll",
    ]
    binaries = []
    for name in names:
        path = os.path.join(CONDA_BIN, name)
        if os.path.isfile(path):
            binaries.append((path, "."))
    return binaries


a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    binaries=_collect_runtime_binaries(),
    datas=[],
    hiddenimports=[
        "PyQt5",
        "PyQt5.QtCore",
        "PyQt5.QtGui",
        "PyQt5.QtWidgets",
        "requests",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "torch",
        "transformers",
        "datasets",
        "peft",
        "accelerate",
        "bitsandbytes",
        "numpy.distutils",
        "matplotlib",
        "pytest",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="EmailLLMAssistant",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements=None,
)
