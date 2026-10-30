"""各測試共用的 fixture"""
import os
import sys
from pathlib import Path

import pytest


@pytest.fixture
def exe_dir(tmp_path, monkeypatch):
    """模擬 PyInstaller 打包後的執行環境：helper.exe 放在 tmp_path"""
    exe = tmp_path / 'helper.exe'
    exe.write_text('')
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(exe))
    return tmp_path


@pytest.fixture
def home(tmp_path, monkeypatch):
    """日誌寫在 <home>\\Desktop\\QT_TOOL_LOGS；改到暫存資料夾，不碰真正的桌面"""
    monkeypatch.setattr(Path, 'home', staticmethod(lambda: tmp_path))
    return tmp_path


@pytest.fixture
def root():
    """隱藏的 Tk 主視窗；測試結束時若程式還沒關閉它，就由這裡關閉"""
    tk = pytest.importorskip('tkinter')
    # 只有確定沒有顯示環境時才略過（例如 Linux CI）；其他建立失敗一律讓測試失敗，不可靜默略過
    if sys.platform != 'win32' and not os.environ.get('DISPLAY'):
        pytest.skip('沒有顯示環境（DISPLAY）')
    root = tk.Tk()
    root.withdraw()
    yield root
    try:
        root.destroy()
    except tk.TclError:
        pass  # 程式已經自己關閉視窗
