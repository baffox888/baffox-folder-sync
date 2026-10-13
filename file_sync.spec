# -*- mode: python ; coding: utf-8 -*-
# 用法: pyinstaller file_sync.spec   （图标可选：把 sync.ico 放在本目录即可）
import os

icon_file = 'sync.ico' if os.path.exists('sync.ico') else None

a = Analysis(
    ['file_sync.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['send2trash'],
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
    a.binaries,
    a.datas,
    [],
    name='BaffoxFolderSync',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_file,
)
