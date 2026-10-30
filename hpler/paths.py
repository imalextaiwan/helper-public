"""exe 位置、資源資料夾、桌面與「下載」資料夾（設計第 3 節）

2.0.x 以 config.ini 判斷資源資料夾（Helper\\ 優先），程式在 release/2.0 分支。
"""

import sys
from pathlib import Path


def get_current_dir():
    """取得 exe / 主程式 .py 所在的資料夾"""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    else:
        # 本檔位於 hpler\ 子資料夾，主程式在上一層
        return Path(__file__).parent.parent.absolute()


# 資源資料夾的名稱，依優先順序：helper_software 是 3.0 的預設名稱，
# Helper 再保留一個版本（FR-22）
RESOURCE_DIRS = ('helper_software', 'Helper')
SOFTWARE_XML = 'software.xml'

FOLDERID_DESKTOP = '{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}'
FOLDERID_DOWNLOADS = '{374DE290-123F-4565-9164-39C4925E467B}'


def find_resource_dir() -> Path:
    """資源資料夾：依序找 helper_software\\、Helper\\ 裡的 software.xml，
    再找執行檔旁邊的 software.xml（DD8）。一律以執行檔的位置為準，不受目前
    工作目錄影響（FR-13）。

    都找不到時回傳第 1 順位的路徑，讓錯誤訊息指出預期的位置。
    """
    exe_dir = get_current_dir()
    for name in RESOURCE_DIRS:
        if (exe_dir / name / SOFTWARE_XML).is_file():
            return exe_dir / name
    if (exe_dir / SOFTWARE_XML).is_file():
        return exe_dir
    return exe_dir / RESOURCE_DIRS[0]


def known_folder(folder_id: str) -> Path | None:
    """以 Windows 的 SHGetKnownFolderPath 取得已知資料夾；非 Windows 或取得失敗時回傳 None"""
    if sys.platform != 'win32':
        return None
    # 只有 Windows 用得到，在這裡才 import
    import ctypes
    import uuid
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [('Data1', wintypes.DWORD), ('Data2', wintypes.WORD),
                    ('Data3', wintypes.WORD), ('Data4', ctypes.c_ubyte * 8)]

    shell32 = ctypes.WinDLL('shell32')
    ole32 = ctypes.WinDLL('ole32')
    shell32.SHGetKnownFolderPath.argtypes = [ctypes.POINTER(GUID), wintypes.DWORD,
                                             wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
    shell32.SHGetKnownFolderPath.restype = ctypes.c_long  # HRESULT
    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]

    guid = GUID.from_buffer_copy(uuid.UUID(folder_id).bytes_le)
    buffer = ctypes.c_void_p()
    hr = shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(buffer))
    try:
        # 失敗時（例如不認得的資料夾）不會配置記憶體，buffer 是 NULL
        return Path(ctypes.wstring_at(buffer.value)) if hr == 0 and buffer.value else None
    finally:
        ole32.CoTaskMemFree(buffer)


def desktop_dir() -> Path:
    """桌面。開啟 OneDrive 備份桌面時，實際的桌面在 OneDrive\\Desktop，
    用「使用者資料夾\\Desktop」會寫到看不見的位置（DD10）"""
    return known_folder(FOLDERID_DESKTOP) or Path.home() / 'Desktop'


def downloads_dir() -> Path:
    """「下載」資料夾：執行時的暫存資料夾放在這裡（設計第 7.7 節、DD13）"""
    return known_folder(FOLDERID_DOWNLOADS) or Path.home() / 'Downloads'
