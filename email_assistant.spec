# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec：将《本地智能邮件分类与回复助手》打包为单目录或单文件 exe。
# 用法: pyinstaller email_assistant.spec

import os
import sys

# 项目根目录（PyInstaller 执行 spec 时自动注入 SPEC 变量，为当前 spec 文件路径）
ROOT = os.path.dirname(os.path.abspath(SPEC))
CONDA_BIN = os.path.join(sys.base_prefix, 'Library', 'bin')


def _collect_runtime_binaries():
    """收集 Conda/PyQt5 运行所需的核心 DLL，避免打包后 QtWidgets 加载失败。"""
    names = [
        'Qt5Core_conda.dll',
        'Qt5Gui_conda.dll',
        'Qt5Widgets_conda.dll',
        'Qt5Network_conda.dll',
        'Qt5Svg_conda.dll',
        'Qt5DBus_conda.dll',
        'Qt5PrintSupport_conda.dll',
        'libjpeg.dll',
        'libpng16.dll',
        'libcrypto-3-x64.dll',
        'libssl-3-x64.dll',
        'libbz2.dll',
        'ffi.dll',
        'zstd.dll',
    ]
    binaries = []
    for name in names:
        path = os.path.join(CONDA_BIN, name)
        if os.path.isfile(path):
            binaries.append((path, '.'))
    return binaries

# 若使用本地 transformers 模型，将模型路径加入 datas，否则 exe 需从环境变量或配置文件读模型路径
# 示例：模型在 D:\models\Llama-3.2-1B
# MODEL_PATH = r'D:\models\Llama-3.2-1B'
# 此处不打包模型（体积巨大），改为运行时从环境变量 LLAMA_MODEL_PATH 或默认 HuggingFace 缓存读取
# 若需将模型打进包：a = Analysis(..., datas=[(MODEL_PATH, 'models/Llama-3.2-1B')], ...)

a = Analysis(
    [os.path.join(ROOT, 'main.py')],
    pathex=[ROOT],
    binaries=_collect_runtime_binaries(),
    datas=[
        # 可选：打包额外资源
        # (os.path.join(ROOT, 'config'), 'config'),
    ],
    hiddenimports=[
        'PyQt5',
        'PyQt5.QtCore',
        'PyQt5.QtGui',
        'PyQt5.QtWidgets',
        'transformers',
        'torch',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 减小体积：排除不需要的模块（按需启用）
        # 'matplotlib', 'numpy.distutils', 'pytest', 'setuptools',
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
    name='EmailLLMAssistant',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,   # 使用 UPX 压缩，若报错可改为 False
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,   # 无控制台窗口（GUI）
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements=None,
)

# 若希望打包为“单目录”（多个文件，启动更快、体积略大）：注释上面 EXE，改用下面两段：
# exe = EXE(pyz, a.scripts, [], name='EmailLLMAssistant', console=False)
# coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=True, upx_exclude=[], name='EmailLLMAssistant')
