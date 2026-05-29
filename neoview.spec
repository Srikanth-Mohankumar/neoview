# -*- mode: python ; coding: utf-8 -*-

import os
from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

project_root = os.getcwd()

block_cipher = None

datas = []
binaries = []
hiddenimports = []

# Packaged neoview assets (icon, etc.)
datas += collect_data_files("neoview")
# PyMuPDF ships compiled libmupdf bindings that PyInstaller does not pick up
# from a plain `import fitz` — collect them explicitly.
binaries += collect_dynamic_libs("fitz")
datas += collect_data_files("fitz")
hiddenimports += collect_submodules("fitz")
# PySide6 Qt plugins (platform, imageformats) need to ride along on Windows.
hiddenimports += [
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtSvg",
]


a = Analysis(
    [os.path.join(project_root, "src", "neoview", "__main__.py")],
    pathex=[os.path.join(project_root, "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="neoview",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(project_root, "src", "neoview", "assets", "feather-logo.ico"),
)
