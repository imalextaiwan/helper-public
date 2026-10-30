"""路徑規則（設計第 3 節，FR-10～FR-13、FR-22、FR-46；DD8、DD10、DD13）

以 software.xml 判斷資源資料夾，helper_software\\ 優先；桌面與「下載」資料夾以
Windows 的已知資料夾 API 取得。
"""
import os
import sys
from pathlib import Path

import pytest

from hpler import paths
from hpler.paths import RESOURCE_DIRS, desktop_dir, downloads_dir, find_resource_dir, get_current_dir

REPO_ROOT = Path(__file__).resolve().parent.parent

windows_only = pytest.mark.skipif(sys.platform != 'win32', reason='已知資料夾 API 只有 Windows 有')


def make_resource_dir(path, file_name='software.xml'):
    path.mkdir(parents=True, exist_ok=True)
    (path / file_name).write_text('<software/>', encoding='utf-8')


# ========== 執行檔的位置 ==========

def test_current_dir_frozen_is_exe_folder(exe_dir):
    assert get_current_dir() == exe_dir


def test_current_dir_unfrozen_is_main_script_folder(monkeypatch):
    monkeypatch.delattr(sys, 'frozen', raising=False)
    assert get_current_dir().resolve() == REPO_ROOT


# ========== 資源資料夾 ==========

def test_resource_dir_names_in_priority_order():
    assert RESOURCE_DIRS == ('helper_software', 'Helper')


def test_helper_software(exe_dir):
    make_resource_dir(exe_dir / 'helper_software')
    assert find_resource_dir() == exe_dir / 'helper_software'


def test_helper_kept_for_one_more_version(exe_dir):
    make_resource_dir(exe_dir / 'Helper')
    assert find_resource_dir() == exe_dir / 'Helper'


def test_both_folders_prefer_helper_software(exe_dir):
    """FR-22：同時存在時載入 helper_software 的內容（2.0.x 是 Helper 優先）"""
    make_resource_dir(exe_dir / 'Helper')
    make_resource_dir(exe_dir / 'helper_software')
    assert find_resource_dir() == exe_dir / 'helper_software'


def test_software_xml_next_to_exe(exe_dir):
    """DD8：和 2.0 一樣，仍接受設定檔和執行檔放在同一層"""
    (exe_dir / 'software.xml').write_text('<software/>', encoding='utf-8')
    assert find_resource_dir() == exe_dir


def test_folder_without_software_xml_is_skipped(exe_dir):
    (exe_dir / 'helper_software').mkdir()
    make_resource_dir(exe_dir / 'Helper')
    assert find_resource_dir() == exe_dir / 'Helper'


def test_nothing_found_points_to_first_choice(exe_dir):
    """找不到時回傳第 1 順位的路徑，錯誤訊息才會指出預期的位置"""
    assert find_resource_dir() == exe_dir / 'helper_software'


def test_ini_is_not_a_3_0_settings_file(exe_dir):
    """FR-21：3.0 只讀 XML。只有 config.ini 的 2.0 佈局，對 3.0 來說是找不到設定檔"""
    make_resource_dir(exe_dir / 'Helper', 'config.ini')
    assert find_resource_dir() == exe_dir / 'helper_software'


def test_independent_of_current_directory(exe_dir, tmp_path_factory, monkeypatch):
    """FR-13：從捷徑或其他資料夾啟動，結果相同"""
    make_resource_dir(exe_dir / 'helper_software')
    monkeypatch.chdir(tmp_path_factory.mktemp('elsewhere'))
    assert find_resource_dir() == exe_dir / 'helper_software'


# ========== 桌面與「下載」資料夾 ==========

def shell_folder(value_name):
    """登錄裡的 User Shell Folders：和已知資料夾 API 是不同的取得方式，用來交叉比對"""
    import winreg
    key = r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders'
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
        return Path(os.path.expandvars(winreg.QueryValueEx(k, value_name)[0]))


@windows_only
def test_desktop_matches_shell_folders():
    assert desktop_dir() == shell_folder('Desktop')


@windows_only
def test_downloads_matches_shell_folders():
    assert downloads_dir() == shell_folder('{374DE290-123F-4565-9164-39C4925E467B}')


@windows_only
def test_unknown_known_folder_returns_none():
    assert paths.known_folder('{00000000-0000-0000-0000-000000000000}') is None


def test_fallback_when_known_folder_is_unavailable(monkeypatch, tmp_path):
    """非 Windows（測試環境），或 API 失敗時，改用使用者資料夾底下的預設位置"""
    monkeypatch.setattr(paths, 'known_folder', lambda guid: None)
    monkeypatch.setattr(Path, 'home', staticmethod(lambda: tmp_path))
    assert desktop_dir() == tmp_path / 'Desktop'
    assert downloads_dir() == tmp_path / 'Downloads'
