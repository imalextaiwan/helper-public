"""權限（設計第 10 節；FR-01、FR-02）

打包後的執行檔由 manifest 要求提權（DD1），程式裡不需要再處理；直接執行 .py
（只用於開發）時，以 ShellExecuteW 的 runas 重新啟動自己。
"""
import ctypes
import subprocess
import sys

import pytest

from hpler import admin

windows_only = pytest.mark.skipif(sys.platform != 'win32', reason='需要 Windows')


class FakeShellExecute:
    def __init__(self, code):
        self.code = code
        self.calls = []

    def __call__(self, file, params):
        self.calls.append((file, params))
        return self.code


@windows_only
def test_is_admin_matches_windows():
    assert admin.is_admin() == bool(ctypes.windll.shell32.IsUserAnAdmin())


@pytest.mark.parametrize('frozen, elevated, expected', [
    (True, False, False),    # 打包後：manifest 已經要求提權，不需要重新啟動
    (True, True, False),
    (False, True, False),    # 直接執行 .py，已經是系統管理員
    (False, False, True),    # 直接執行 .py，不是系統管理員：重新啟動
])
def test_needs_relaunch(monkeypatch, frozen, elevated, expected):
    monkeypatch.setattr(admin, 'is_admin', lambda: elevated)
    assert admin.needs_relaunch(frozen=frozen) is expected


def test_relaunch_quotes_paths_with_spaces(tmp_path):
    """修正 2.0：主程式的路徑含空白時，參數不會被斷開"""
    script = tmp_path / 'my tools' / 'helper.py'
    fake = FakeShellExecute(42)

    error = admin.relaunch_as_admin(script, ['--flag', 'value with space'], shell_execute=fake)

    assert error is None
    [(file, params)] = fake.calls
    assert file == sys.executable
    assert params == subprocess.list2cmdline([str(script.resolve()), '--flag', 'value with space'])
    assert params.startswith('"')


@pytest.mark.parametrize('code, words', [
    (5, '否'),          # 使用者在 UAC 按了「否」
    (2, '找不到檔案'),
    (999 % 33, '代碼'),  # 不認得的代碼也要顯示
])
def test_relaunch_failure_explains_why(tmp_path, code, words):
    error = admin.relaunch_as_admin(tmp_path / 'helper.py', [], shell_execute=FakeShellExecute(code))
    assert error is not None and words in error and str(code) in error
