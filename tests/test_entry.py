"""進入點 helper.py（設計第 6.1、10、13 節；FR-01、FR-02、FR-13、FR-14、FR-22）

介面函式換成記錄呼叫的假物件：不開視窗、不提權，只驗證啟動流程。
"""
import re
import shutil
import sys
from pathlib import Path

import pytest

pytest.importorskip('tkinter')
pytest.importorskip('PIL.ImageTk')

import helper  # noqa: E402  需要先確認有 tkinter 和 Pillow
from hpler import admin, config, gui  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / 'fixtures' / 'valid'


@pytest.fixture
def calls(monkeypatch):
    """記錄進入點呼叫了哪些介面函式；預設已經是系統管理員"""
    calls = []
    monkeypatch.setattr(gui, 'run', lambda load, **kw: calls.append(('run', load, kw)))
    monkeypatch.setattr(gui, 'show_fatal', lambda *args: calls.append(('show_fatal', *args)))
    monkeypatch.setattr(gui, 'show_error', lambda *args: calls.append(('show_error', *args)))
    monkeypatch.setattr(admin, 'is_admin', lambda: True)
    return calls


# ========== 讀取設定、啟動介面 ==========

def test_starts_the_gui_with_the_resource_folder(exe_dir, calls):
    shutil.copytree(FIXTURE, exe_dir / 'helper_software')
    assert helper.main([]) == 0
    [(name, load, kwargs)] = calls
    assert name == 'run' and kwargs == {'is_admin': True}
    assert load.resource_dir == exe_dir / 'helper_software'
    assert [s.id for s in load.software] and [c.id for c in load.categories]


def test_helper_folder_is_still_accepted(exe_dir, calls):
    """FR-22：Helper\\ 再保留一個版本"""
    shutil.copytree(FIXTURE, exe_dir / 'Helper')
    assert helper.main([]) == 0
    assert calls[0][0] == 'run' and calls[0][1].resource_dir == exe_dir / 'Helper'


def test_independent_of_current_directory(exe_dir, calls, tmp_path_factory, monkeypatch):
    """FR-13：從捷徑或其他資料夾啟動，結果相同"""
    shutil.copytree(FIXTURE, exe_dir / 'helper_software')
    monkeypatch.chdir(tmp_path_factory.mktemp('elsewhere'))
    assert helper.main([]) == 0
    assert calls[0][1].resource_dir == exe_dir / 'helper_software'


def test_warnings_do_not_stop_startup(exe_dir, calls):
    """有問題但不是 fatal：照常啟動，由介面顯示問題清單（FR-36）"""
    shutil.copytree(FIXTURE, exe_dir / 'helper_software')
    (exe_dir / 'helper_software' / 'tasks' / 'unregistered.cmd').write_bytes(b'')
    assert helper.main([]) == 0
    [(name, load, _)] = calls
    assert name == 'run' and any('unregistered.cmd' in p.message for p in load.problems)


def test_admin_state_is_passed_to_the_gui(exe_dir, calls, monkeypatch):
    """寫進日誌的權限狀態（設計第 8 節）"""
    shutil.copytree(FIXTURE, exe_dir / 'helper_software')
    monkeypatch.setattr(admin, 'is_admin', lambda: False)
    helper.main([])
    assert calls[0][2] == {'is_admin': False}


# ========== 找不到或無法讀取設定檔（FR-14） ==========

def test_missing_settings_show_the_expected_layout_and_exit(exe_dir, calls):
    assert helper.main([]) == 1
    [(name, problems, folder, program)] = calls
    assert name == 'show_fatal' and folder == exe_dir and program == 'helper.exe'
    assert any(p.severity == 'fatal' for p in problems)


def test_broken_software_xml_exits(exe_dir, calls):
    shutil.copytree(FIXTURE, exe_dir / 'helper_software')
    (exe_dir / 'helper_software' / 'software.xml').write_text('<software>', encoding='utf-8')
    assert helper.main([]) == 1
    assert [c[0] for c in calls] == ['show_fatal']


def test_program_name_in_messages(exe_dir, monkeypatch):
    """打包後是執行檔的名稱，直接執行時是 helper.py"""
    assert helper.program_name() == 'helper.exe'
    monkeypatch.delattr(sys, 'frozen')
    assert helper.program_name() == 'helper.py'


# ========== 直接執行 .py 時的提權（設計第 10 節，FR-01） ==========

def test_relaunches_as_admin_and_exits(calls, monkeypatch):
    relaunched = []
    monkeypatch.setattr(admin, 'needs_relaunch', lambda: True)
    monkeypatch.setattr(admin, 'relaunch_as_admin', lambda script, args: relaunched.append((script, args)))
    monkeypatch.setattr(config, 'load', lambda resource_dir: pytest.fail('不應該在原本的行程讀設定'))
    assert helper.main(['--x', 'a b']) == 0
    assert relaunched == [(Path(helper.__file__), ['--x', 'a b'])]
    assert calls == []


def test_relaunch_failure_is_shown(calls, monkeypatch):
    monkeypatch.setattr(admin, 'needs_relaunch', lambda: True)
    monkeypatch.setattr(admin, 'relaunch_as_admin', lambda script, args: '無法以系統管理員身分重新啟動（代碼 5）')
    assert helper.main([]) == 1
    [(name, title, message)] = calls
    assert name == 'show_error' and '代碼 5' in message


def test_packaged_exe_does_not_relaunch(exe_dir, calls, monkeypatch):
    """FR-02：打包後由執行檔的宣告要求提權，程式裡不再重新啟動"""
    shutil.copytree(FIXTURE, exe_dir / 'helper_software')
    monkeypatch.setattr(admin, 'is_admin', lambda: False)
    monkeypatch.setattr(admin, 'relaunch_as_admin', lambda script, args: pytest.fail('不應該重新啟動'))
    assert helper.main([]) == 0
    assert calls[0][0] == 'run'


# ========== 非預期的錯誤（設計第 13 節） ==========

def test_unexpected_error_is_shown_with_traceback(exe_dir, calls, monkeypatch):
    """打包後沒有主控台：錯誤內容要顯示出來，不能只印到看不到的地方"""
    def broken(resource_dir):
        raise RuntimeError('壞掉了')

    monkeypatch.setattr(config, 'load', broken)
    assert helper.main([]) == 1
    [(name, title, message)] = calls
    assert name == 'show_error' and 'RuntimeError: 壞掉了' in message and 'Traceback' in message


# ========== 打包設定（FR-02、FR-22、NFR-02） ==========

def test_spec_builds_helper_exe_that_requires_admin():
    spec = (REPO_ROOT / 'helper.spec').read_text(encoding='utf-8')
    assert re.search(r"^\s*name='helper',", spec, re.MULTILINE)
    assert "StringStruct('OriginalFilename', 'helper.exe')" in spec
    assert re.search(r'^\s*uac_admin=True,', spec, re.MULTILINE)
    assert re.search(r"^\s*\['helper\.py'\],", spec, re.MULTILINE)
