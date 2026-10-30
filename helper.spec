# -*- mode: python ; coding: utf-8 -*-
"""Helper 打包設定（PyInstaller）

在 repo 根目錄執行：

    pyinstaller --clean --noconfirm helper.spec

產生 dist\\helper.exe（FR-22 的預設名稱）：單一執行檔、要求系統管理員權限（DD1）、x64、
附圖示與版本資訊（設計第 12 節）。
"""

import re
import struct
import sys
from pathlib import Path

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

ROOT = Path(SPECPATH)

# DD11、C-02：Windows 上執行檔的架構跟著打包用的 Python，所以只接受 3.12 x64
if sys.version_info[:2] != (3, 12) or struct.calcsize('P') != 8:
    raise SystemExit(f'helper.spec 需要 Python 3.12 x64，目前是 {sys.version.split()[0]}'
                     f'（{struct.calcsize("P") * 8} 位元）')

# 產品名稱與版本號只寫在 hpler/__init__.py；用文字讀取，不 import，避免打包時執行程式碼
INIT = (ROOT / 'hpler' / '__init__.py').read_text(encoding='utf-8')
VERSION = re.search(r"^__version__ = '(\d+)\.(\d+)\.(\d+)'$", INIT, re.MULTILINE)
if VERSION is None:
    raise SystemExit("helper.spec 在 hpler/__init__.py 找不到 __version__ = 'X.Y.Z'")
VERSION_TUPLE = tuple(int(n) for n in VERSION.groups()) + (0,)
VERSION_TEXT = '.'.join(VERSION.groups())
PRODUCT = re.search(r"^PRODUCT_NAME = '([^']+)'$", INIT, re.MULTILINE)
if PRODUCT is None:
    raise SystemExit("helper.spec 在 hpler/__init__.py 找不到 PRODUCT_NAME = '名稱'")
PRODUCT_NAME = PRODUCT.group(1)

version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=VERSION_TUPLE, prodvers=VERSION_TUPLE),
    kids=[
        # 040404B0：繁體中文（台灣）、Unicode
        StringFileInfo([StringTable('040404B0', [
            StringStruct('CompanyName', 'Automation Team'),
            StringStruct('FileDescription', f'{PRODUCT_NAME} 軟體安裝與系統設定工具'),
            StringStruct('FileVersion', VERSION_TEXT),
            StringStruct('InternalName', 'helper'),
            StringStruct('OriginalFilename', 'helper.exe'),
            StringStruct('ProductName', PRODUCT_NAME),
            StringStruct('ProductVersion', VERSION_TEXT),
        ])]),
        VarFileInfo([VarStruct('Translation', [0x0404, 1200])]),
    ],
)

# tkinter 的 tcl/tk 由 PyInstaller 內建的 hook 收進執行檔，不需要像 2.0 那樣以 datas 指定本機路徑
a = Analysis(
    ['helper.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
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
    name='helper',
    icon=str(ROOT / 'assets' / 'helper_icon.ico'),
    version=version_info,
    uac_admin=True,             # DD1：由 Windows 在啟動前要求提權（FR-02）
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                  # 不壓縮：結果不依賴打包電腦有沒有安裝 UPX（NFR-08）
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,              # 和 2.0 相同：不顯示主控台視窗
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
