# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for a double-clickable macOS .app (no Terminal window).
From repository root:  pyinstaller packaging/dj-mm.spec
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

SPEC_DIR = Path(SPEC).resolve().parent
ROOT = SPEC_DIR.parent

datas = [
    (str(ROOT / "static"), "static"),
    (str(ROOT / "config.json.example"), "."),
]
binaries = []
hiddenimports = []
for pkg in ("werkzeug", "flask"):
    tmp_ret = collect_all(pkg)
    datas += tmp_ret[0]
    binaries += tmp_ret[1]
    hiddenimports += tmp_ret[2]

block_cipher = None

a = Analysis(
    [str(ROOT / "launch_gui.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DJMetaManager",
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
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="DJMetaManager",
)

app = BUNDLE(
    coll,
    name="DJ MetaManager.app",
    icon=None,
    bundle_identifier="com.djmetamanager.app",
)
