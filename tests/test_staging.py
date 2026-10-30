"""暫存資料夾（設計第 7.7 節；FR-46～FR-48、NFR-07）

執行前先把軟體子資料夾複製到「下載」底下這一輪專屬的暫存資料夾，結束後刪除。
工具以管理員權限執行，刪錯會造成無法復原的損失：只刪除符合四個條件的資料夾。
"""
import ctypes
import os
import shutil
import stat
import subprocess
import sys
from collections import namedtuple
from datetime import datetime
from pathlib import Path

import pytest

import hpler
from hpler import staging
from hpler.models import Software, SystemTask

windows_only = pytest.mark.skipif(sys.platform != 'win32', reason='需要 Windows')
GB = 1024 ** 3


@pytest.fixture
def downloads(tmp_path):
    path = tmp_path / 'Downloads'
    path.mkdir()
    return path


@pytest.fixture
def res(tmp_path):
    """資源資料夾：cpu-z（兩個檔案）、tools\\vc（一個檔案）、desk（不先複製）、tasks\\"""
    res = tmp_path / 'helper_software'
    (res / 'cpu-z' / 'sub').mkdir(parents=True)
    (res / 'cpu-z' / 'setup.exe').write_bytes(b'x' * 1000)
    (res / 'cpu-z' / 'sub' / 'data.bin').write_bytes(b'y' * 500)
    (res / 'tools' / 'vc').mkdir(parents=True)
    (res / 'tools' / 'vc' / 'vc.exe').write_bytes(b'z' * 300)
    (res / 'desk').mkdir()
    (res / 'desk' / 'desk.exe').write_bytes(b'd' * 7000)
    (res / 'tasks').mkdir()
    (res / 'tasks' / 'power_001.cmd').write_bytes(b'@echo off\r\nexit /b 0\r\n')
    return res


def software(res, folder, exe, copy_first=True):
    return Software(id=folder.replace('\\', '_').replace('-', '_'), name=folder,
                    folder=res.joinpath(*folder.split('\\')), executable=res.joinpath(*folder.split('\\'), exe),
                    copy_first=copy_first)


LEGACY_MARKER = '.hpler_staging'  # 3.0.0、3.0.1 的標記檔（設計第 2.4 節）


def make_stage(downloads, name='Helper_20261022_100000', marker=staging.MARKER):
    """marker 是標記檔的名稱；None 表示沒有標記檔"""
    stage = downloads / name
    stage.mkdir()
    if marker:
        (stage / marker).write_text('Helper', encoding='utf-8')
    return stage


# ========== 空間檢查（FR-47） ==========

def test_required_bytes_counts_only_items_copied_first(res):
    items = [software(res, 'cpu-z', 'setup.exe'), software(res, 'tools\\vc', 'vc.exe'),
             software(res, 'desk', 'desk.exe', copy_first=False)]
    assert staging.required_bytes(items) == 1000 + 500 + 300


def test_required_bytes_for_tasks(res):
    task = SystemTask(id='power_001', name='x', description='', script=res / 'tasks' / 'power_001.cmd')
    assert staging.required_bytes([task]) == len(b'@echo off\r\nexit /b 0\r\n')


def test_enough_space(downloads, monkeypatch):
    usage = namedtuple('usage', 'total used free')
    monkeypatch.setattr(staging.shutil, 'disk_usage', lambda path: usage(100 * GB, 50 * GB, 50 * GB))
    assert staging.check_space(downloads, 10 * GB) is None


def test_not_enough_space_includes_margin(downloads, monkeypatch):
    """加上 1 GB 餘裕再比較；訊息列出需要與可用的空間"""
    usage = namedtuple('usage', 'total used free')
    monkeypatch.setattr(staging.shutil, 'disk_usage', lambda path: usage(100 * GB, 90 * GB, 10 * GB))
    reason = staging.check_space(downloads, int(9.5 * GB))
    assert reason is not None
    assert '10.5 GB' in reason and '10.0 GB' in reason


# ========== 建立暫存資料夾 ==========

def test_create(downloads, monkeypatch):
    class FrozenClock:
        @staticmethod
        def now():
            return datetime(2026, 10, 22, 10, 0, 0)

    monkeypatch.setattr(staging, 'datetime', FrozenClock)
    first = staging.create(downloads, secure=False)
    second = staging.create(downloads, secure=False)

    assert first == downloads / 'Helper_20261022_100000'
    assert second == downloads / 'Helper_20261022_100000_2'  # 同一秒內再建立一個
    assert staging.MARKER == '.helper_staging'
    marker = (first / staging.MARKER).read_text(encoding='utf-8')
    assert f'Helper {hpler.__version__}' in marker and str(os.getpid()) in marker


def is_elevated():
    return sys.platform == 'win32' and bool(ctypes.windll.shell32.IsUserAnAdmin())


@windows_only
def test_create_secure_blocks_normal_users(downloads):
    """NFR-07：一般權限的程式無法在暫存資料夾裡寫入（不然可以在執行前替換安裝檔）"""
    if is_elevated():
        pytest.skip('以系統管理員身分執行時無法驗證「一般使用者不能寫入」')
    stage = staging.create(downloads, secure=True)
    try:
        with pytest.raises(PermissionError):
            (stage / 'planted.exe').write_bytes(b'x')
    finally:
        # 建立者是擁有者，仍然可以改回權限，測試結束時清理
        subprocess.run(['icacls', str(stage), '/reset', '/T', '/Q'], check=True, capture_output=True)
        shutil.rmtree(stage)


def sddl(path):
    """路徑的擁有者與 DACL，以 SDDL 表示"""
    from ctypes import wintypes
    advapi32 = ctypes.WinDLL('advapi32', use_last_error=True)
    advapi32.GetNamedSecurityInfoW.argtypes = [wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD, ctypes.c_void_p,
                                               ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                               ctypes.POINTER(ctypes.c_void_p)]
    advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(wintypes.LPWSTR), ctypes.c_void_p]
    sd = ctypes.c_void_p()
    assert advapi32.GetNamedSecurityInfoW(str(path), 1, 0x5, None, None, None, None, ctypes.byref(sd)) == 0
    text = wintypes.LPWSTR()
    assert advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW(sd, 1, 0x5, ctypes.byref(text), None)
    value = text.value
    ctypes.windll.kernel32.LocalFree(text)
    ctypes.windll.kernel32.LocalFree(sd)
    return value


def dacl_sids(path):
    return sorted(ace.split(';')[-1] for ace in sddl(path).split('D:', 1)[1].strip('PAI').strip('()').split(')('))


def unrestrict(path):
    """測試結束時清理：建立者（擁有者）把權限改回繼承"""
    subprocess.run(['icacls', str(path), '/reset', '/T', '/Q'], capture_output=True)
    shutil.rmtree(path, ignore_errors=True)


@windows_only
def test_restrict_replaces_every_other_permission(tmp_path):
    """T44 驗收發現：「下載」裡的子資料夾，使用者的完整控制 icacls /inheritance:r 移除不掉，
    一般權限的程式仍然可以寫入。不論原本有什麼權限，最後只能有 Administrators 與 SYSTEM"""
    folder = tmp_path / 'Helper_20261024_100000'
    folder.mkdir()
    (folder / staging.MARKER).write_text('Helper', encoding='utf-8')
    user = subprocess.run(['whoami', '/user', '/fo', 'csv', '/nh'], capture_output=True, text=True,
                          check=True).stdout.split(',')[1].strip().strip('"')
    # 和「下載」裡的情況相同：使用者的完整控制不是繼承來的
    subprocess.run(['icacls', str(folder), '/grant', f'*{user}:(OI)(CI)F'], check=True, capture_output=True)
    try:
        staging._restrict_to_admins(folder)
        assert sddl(folder).split('D:', 1)[1].startswith('P')  # 禁止繼承
        assert dacl_sids(folder) == ['BA', 'SY']
        assert dacl_sids(folder / staging.MARKER) == ['BA', 'SY']
        if not is_elevated():
            with pytest.raises(PermissionError):
                (folder / 'planted.exe').write_bytes(b'x')
    finally:
        unrestrict(folder)


@windows_only
def test_create_secure_permissions(downloads):
    stage = staging.create(downloads, secure=True)
    try:
        assert dacl_sids(stage) == ['BA', 'SY'] and dacl_sids(stage / staging.MARKER) == ['BA', 'SY']
        if is_elevated():  # 擁有者一定可以改權限，所以擁有者要是 Administrators（設計第 7.7 節）
            assert sddl(stage).startswith('O:BA')
    finally:
        unrestrict(stage)


# ========== 複製（FR-46、FR-47） ==========

def test_copy_software_keeps_relative_folder(res, downloads):
    stage = make_stage(downloads)
    item = software(res, 'tools\\vc', 'vc.exe')

    result = staging.copy_software(stage, res, item)

    assert result.error is None
    assert (result.files, result.size_bytes) == (1, 300)
    assert result.destination == stage / 'tools' / 'vc'
    assert result.item.folder == stage / 'tools' / 'vc'
    assert result.item.executable == stage / 'tools' / 'vc' / 'vc.exe'
    assert result.item.id == item.id and result.item.icon == item.icon  # 其他欄位不變
    assert (stage / 'tools' / 'vc' / 'vc.exe').read_bytes() == b'z' * 300


def test_copy_software_with_subfolders(res, downloads):
    result = staging.copy_software(make_stage(downloads), res, software(res, 'cpu-z', 'setup.exe'))
    assert (result.files, result.size_bytes) == (2, 1500)
    assert (result.destination / 'sub' / 'data.bin').exists()


def test_copy_failure_removes_partial_copy(res, downloads, monkeypatch):
    stage = make_stage(downloads)
    real_copy2 = shutil.copy2

    def failing_copy2(src, dst, **kwargs):
        if Path(src).name == 'data.bin':
            raise OSError(28, '模擬：磁碟已滿')
        return real_copy2(src, dst, **kwargs)

    monkeypatch.setattr(staging.shutil, 'copy2', failing_copy2)
    result = staging.copy_software(stage, res, software(res, 'cpu-z', 'setup.exe'))

    assert result.item is None
    assert '磁碟已滿' in result.error
    assert any('data.bin' in name for name in result.failed_files)
    assert not (stage / 'cpu-z').exists()  # 複製到一半的檔案已刪除


def test_copy_missing_source(res, downloads):
    shutil.rmtree(res / 'cpu-z')
    result = staging.copy_software(make_stage(downloads), res, software(res, 'cpu-z', 'setup.exe'))
    assert result.item is None and result.error


def test_copy_scripts(res, downloads):
    stage = make_stage(downloads)
    task = SystemTask(id='power_001', name='x', description='', script=res / 'tasks' / 'power_001.cmd')

    result = staging.copy_script(stage, task)

    assert result.error is None
    assert result.item.script == stage / 'tasks' / 'power_001.cmd'
    assert result.item.script.read_bytes() == task.script.read_bytes()


# ========== 刪除（FR-48） ==========

def test_cleanup_removes_current_and_old_marked_folders(res, downloads):
    current = make_stage(downloads, 'Helper_20261022_110000')
    (current / 'cpu-z').mkdir()
    (current / 'cpu-z' / 'setup.exe').write_bytes(b'x')
    old = make_stage(downloads, 'Helper_20261021_090000')  # 先前異常結束留下的

    result = staging.cleanup(downloads, current, res)

    assert set(result.removed) == {current, old}
    assert result.leftovers == ()
    assert not current.exists() and not old.exists()


def test_cleanup_removes_folders_left_by_3_0_1(res, downloads):
    """3.0.0、3.0.1 異常結束留下的 Hpler_* 也要刪除，否則會一直留在「下載」裡（FR-23）"""
    current = make_stage(downloads, 'Helper_20261028_110000')
    legacy = make_stage(downloads, 'Hpler_20261027_090000', marker=LEGACY_MARKER)
    (legacy / 'cpu-z').mkdir()
    (legacy / 'cpu-z' / 'setup.exe').write_bytes(b'x')

    result = staging.cleanup(downloads, current, res)

    assert set(result.removed) == {current, legacy}
    assert not legacy.exists()


@pytest.mark.parametrize('name, marker', [
    ('Helper_20261021_090000', None),             # 沒有標記檔
    ('Hpler_20261021_090000', None),              # 舊名稱，沒有標記檔
    ('MyStuff', staging.MARKER),                  # 名稱不是 Helper_、Hpler_ 開頭
    ('Helper_20261021_090000', LEGACY_MARKER),    # 名稱與標記檔不是同一組
    ('Hpler_20261021_090000', staging.MARKER),
], ids=['no-marker', 'legacy-no-marker', 'other-name', 'new-name-old-marker', 'old-name-new-marker'])
def test_cleanup_leaves_folders_it_did_not_create(res, downloads, name, marker):
    other = make_stage(downloads, name, marker=marker)
    result = staging.cleanup(downloads, None, res)
    assert other.exists() and result.removed == ()


def test_cleanup_leaves_nested_marked_folders(res, downloads):
    """只刪除直接位於下載資料夾底下的資料夾"""
    nested = downloads / 'sub'
    nested.mkdir()
    deep = make_stage(nested, 'Helper_20261021_090000')
    staging.cleanup(downloads, None, res)
    assert deep.exists()


def test_cleanup_refuses_resource_dir(downloads, tmp_path):
    """資源資料夾放在下載資料夾、名稱又剛好是 Helper_ 開頭並有標記檔，也不刪"""
    res = make_stage(downloads, 'Helper_resources')
    result = staging.cleanup(downloads, res, res)
    assert res.exists() and result.removed == ()


def test_cleanup_refuses_folder_containing_resource_dir(downloads):
    stage = make_stage(downloads)
    res = stage / 'helper_software'
    res.mkdir()
    staging.cleanup(downloads, stage, res)
    assert res.exists()


@pytest.mark.parametrize('case', ['outside', 'resource', 'inside-resource', 'no-marker', 'name',
                                  'mismatched-marker', 'legacy-outside'])
def test_safety_conditions(downloads, tmp_path, case):
    res = tmp_path / 'helper_software'
    res.mkdir()
    stage = {
        'outside': lambda: make_stage(tmp_path, 'Helper_x'),
        'resource': lambda: res,
        'inside-resource': lambda: make_stage(res, 'Helper_x'),
        'no-marker': lambda: make_stage(downloads, 'Helper_x', marker=None),
        'name': lambda: make_stage(downloads, 'Other_x'),
        'mismatched-marker': lambda: make_stage(downloads, 'Hpler_x', marker=staging.MARKER),
        'legacy-outside': lambda: make_stage(tmp_path, 'Hpler_x', marker=LEGACY_MARKER),
    }[case]()
    assert staging.is_safe_to_delete(stage, downloads, res) is False
    assert staging.is_safe_to_delete(make_stage(downloads, 'Helper_ok'), downloads, res) is True
    legacy = make_stage(downloads, 'Hpler_ok', marker=LEGACY_MARKER)  # 3.0.0、3.0.1 建立的
    assert staging.is_safe_to_delete(legacy, downloads, res) is True


def test_cleanup_removes_read_only_files(res, downloads):
    """複製時保留了唯讀屬性的安裝檔也要刪得掉"""
    stage = make_stage(downloads)
    readonly = stage / 'setup.exe'
    readonly.write_bytes(b'x')
    readonly.chmod(stat.S_IREAD)
    result = staging.cleanup(downloads, stage, res)
    assert result.leftovers == () and not stage.exists()


def test_cleanup_without_current_stage(res, downloads):
    assert staging.cleanup(downloads, None, res).removed == ()


def test_cleanup_when_downloads_missing(res, tmp_path):
    result = staging.cleanup(tmp_path / 'missing', None, res)
    assert result.removed == () and result.leftovers == ()


@windows_only
@pytest.mark.parametrize('name, marker', [
    ('Helper_20261022_100000', staging.MARKER),
    ('Hpler_20261022_100000', LEGACY_MARKER),  # 3.0.1 留下的：保留的是它自己的標記檔
], ids=['current', 'legacy'])
def test_locked_file_is_reported_as_leftover(res, downloads, name, marker):
    """被佔用的檔案重試後仍刪不掉：列在 leftovers，資料夾留著等下一輪"""
    stage = make_stage(downloads, name, marker=marker)
    locked = stage / 'in_use.exe'
    locked.write_bytes(b'x')
    handle = open(locked, 'rb')  # Windows 上開啟中的檔案刪不掉
    current = stage if marker == staging.MARKER else None  # 舊版的資料夾只會是先前留下的
    try:
        result = staging.cleanup(downloads, current, res, retry_seconds=0.5, retry_interval=0.1)
    finally:
        handle.close()
    assert stage.exists()
    assert result.removed == ()
    assert any('in_use.exe' in item for item in result.leftovers)
    assert (stage / marker).exists()  # 標記檔留著，下一輪才認得出來
    # 下一輪再刪：檔案已經不被佔用
    assert staging.cleanup(downloads, None, res).removed == (stage,)


@windows_only
def test_junction_target_is_not_deleted(res, downloads, tmp_path):
    """目錄連結只刪除連結本身，不刪除它指向的內容"""
    import _winapi
    precious = tmp_path / 'precious'
    precious.mkdir()
    (precious / 'keep.txt').write_text('keep')
    stage = make_stage(downloads)
    _winapi.CreateJunction(str(precious), str(stage / 'link'))

    result = staging.cleanup(downloads, stage, res)

    assert result.removed == (stage,)
    assert (precious / 'keep.txt').read_text() == 'keep'
