"""權限（設計第 10 節；FR-01、FR-02）

打包後的 helper.exe 在 manifest 宣告需要系統管理員權限（DD1）：Windows 在程式啟動
之前就跳出 UAC，按「否」程式不會啟動，所以程式裡不需要再檢查。

直接執行 .py（只用於開發）時 manifest 不生效，這裡以 ShellExecuteW 的 runas 重新
啟動自己。顯示錯誤訊息由呼叫端負責（只有 gui 可以 import tkinter）。
"""
from __future__ import annotations

import ctypes
import subprocess
import sys
from pathlib import Path
from typing import Callable, Sequence

# ShellExecuteW 回傳值小於等於 32 時的意思
_SHELL_EXECUTE_ERRORS = {
    0: '系統記憶體或資源不足',
    2: '找不到檔案',
    3: '找不到路徑',
    5: '存取被拒，或在 UAC 視窗按了「否」',
    8: '記憶體不足',
    26: '檔案共用衝突',
    27: '檔案關聯不完整',
    31: '沒有可以開啟這個檔案的應用程式',
    32: '找不到需要的 DLL',
}


def is_admin() -> bool:
    """目前的行程是否以系統管理員身分執行；非 Windows 一律為 False"""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except AttributeError:
        return False


def needs_relaunch(*, frozen: bool | None = None) -> bool:
    """是否要以系統管理員身分重新啟動：只有直接執行 .py、而且不是系統管理員時"""
    if frozen is None:
        frozen = bool(getattr(sys, 'frozen', False))
    return not frozen and not is_admin()


def relaunch_as_admin(script: Path, args: Sequence[str], *,
                      shell_execute: Callable[[str, str], int] | None = None) -> str | None:
    """以系統管理員身分重新啟動 python <script> <args>。

    成功時回傳 None，呼叫端應該立刻結束目前的行程；失敗時回傳原因，由呼叫端顯示後結束。
    參數以 list2cmdline 組成：主程式的路徑含空白時不會被斷開（修正 2.0）。
    """
    params = subprocess.list2cmdline([str(Path(script).resolve()), *args])
    code = (shell_execute or _shell_execute)(sys.executable, params)
    if code > 32:
        return None
    reason = _SHELL_EXECUTE_ERRORS.get(code, '未知的錯誤')
    return f'無法以系統管理員身分重新啟動（代碼 {code}）：{reason}'


def _shell_execute(file: str, params: str) -> int:
    from ctypes import wintypes
    shell_execute = ctypes.windll.shell32.ShellExecuteW
    shell_execute.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
                              wintypes.LPCWSTR, ctypes.c_int]
    shell_execute.restype = ctypes.c_void_p  # HINSTANCE：大於 32 代表成功
    return int(shell_execute(None, 'runas', file, params, None, 1) or 0)  # 1 = SW_SHOWNORMAL
