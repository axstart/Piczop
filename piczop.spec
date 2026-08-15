# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all

datas = [
    ("assets\\piczop.ico", "assets"),
    ("assets\\PiczopLibrary", "PiczopLibrary"),
]
binaries = []
hiddenimports = []
tmp_ret = collect_all("PySide6")
datas += tmp_ret[0]
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]

a = Analysis(
    ["app\\main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports
    + [
        "app",
        "app.ui",
        "app.ui.main_window",
        "app.organize",
        "app.gallery",
        "app.hashing",
        "app.media_meta",
        "app.people",
        "app.suggestions",
        "app.enrich",
        "PIL",
        "PIL.Image",
        "PIL.ImageOps",
        "PIL.ExifTags",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Piczop",
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
    icon="assets\\piczop.ico",
    version="file_version_info.txt",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Piczop",
)
