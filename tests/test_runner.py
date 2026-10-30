"""執行（設計第 7 節；FR-40～FR-48、FR-51、FR-54）

execute：執行一個軟體項目或 .cmd 任務，處理成功代碼、逾時（結束整個行程樹）、輸出解碼。
run_batch：一輪執行的三個階段：複製到暫存資料夾 → 依序執行 → 刪除暫存資料夾（finally）。

假的安裝檔用 Python 本身：可以精確控制結束碼、輸出、逾時與子程式。
"""
import ctypes
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from hpler import paths, runner, staging
from hpler.models import Problem, Software, SystemTask, TaskResult

windows_only = pytest.mark.skipif(sys.platform != 'win32', reason='需要 Windows')
PY = Path(sys.executable)


def python_item(tmp_path, code, *, success_codes=frozenset({0}), item_id='fake', copy_first=False):
    """以 Python 當作安裝檔：args 是 -c "<code>" """
    (tmp_path / 'work').mkdir(exist_ok=True)
    return Software(id=item_id, name=item_id, folder=tmp_path / 'work', executable=PY,
                    args=f'-c "{code}"', success_codes=success_codes, copy_first=copy_first)


def cmd_task(folder, task_id, body):
    folder.mkdir(parents=True, exist_ok=True)
    script = folder / f'{task_id}.cmd'
    script.write_bytes(('@echo off\r\n' + body.replace('\n', '\r\n') + '\r\n').encode('ascii'))
    return SystemTask(id=task_id, name=task_id, description='', script=script)


def is_running(pid):
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    code = ctypes.c_ulong()
    ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(handle)
    return code.value == 259  # STILL_ACTIVE


# ========== 輸出解碼（設計第 7.5 節） ==========

@pytest.mark.parametrize('encoding, data, expected', [
    ('cp950', '測試'.encode('cp950'), '測試'),
    ('cp65001', '測試'.encode('utf-8'), '測試'),
    ('cp950', '測試'.encode('utf-8'), '測試'),    # 固定輸出 UTF-8 的程式（例如 Python 包裝程式）
    ('cp437', '測試'.encode('utf-8'), '測試'),
], ids=['cp950', 'utf8-beta', 'utf8-on-cp950', 'utf8-on-cp437'])
def test_decode_output(monkeypatch, encoding, data, expected):
    monkeypatch.setattr(runner, 'oem_encoding', lambda: encoding)
    assert runner.decode_output(data) == expected


def test_decode_never_fails(monkeypatch):
    monkeypatch.setattr(runner, 'oem_encoding', lambda: 'cp65001')
    assert runner.decode_output(b'\xb4\xfa ok').endswith(' ok')


def test_decode_each_line_separately(monkeypatch):
    """第 7.5 節：同一份輸出裡，cmd.exe 以 OEM 碼頁輸出、Python 工具以 UTF-8 輸出，各行各自讀得懂"""
    monkeypatch.setattr(runner, 'oem_encoding', lambda: 'cp950')
    data = ('系統碼頁的中文\r\n'.encode('cp950') + 'UTF-8 的中文\r\n'.encode('utf-8')
            + '再一行系統碼頁'.encode('cp950'))
    assert runner.decode_output(data) == '系統碼頁的中文\r\nUTF-8 的中文\r\n再一行系統碼頁'


@pytest.mark.parametrize('encoding', ['utf-8', 'cp950'])
def test_decode_keeps_line_endings(monkeypatch, encoding):
    """以 \\r、\\n 分行，換行字元原樣保留（進度列常以 \\r 覆寫同一行）"""
    monkeypatch.setattr(runner, 'oem_encoding', lambda: 'cp950')
    text = '進度 50%\r進度 100%\n完成\r\n\r\n結束'
    assert runner.decode_output(text.encode(encoding)) == text


def test_undecodable_bytes_only_affect_their_line(monkeypatch):
    monkeypatch.setattr(runner, 'oem_encoding', lambda: 'cp950')
    data = 'UTF-8 的中文\n'.encode('utf-8') + b'\xff\xff bad\n' + '系統碼頁的中文'.encode('cp950')
    first, second, third = runner.decode_output(data).splitlines()
    assert (first, third) == ('UTF-8 的中文', '系統碼頁的中文')
    assert second.endswith(' bad') and '�' in second


def test_command_line_keeps_args_verbatim(tmp_path):
    """第 7.2 節：執行檔加上引號，參數原樣接在後面，不切割（DD5）"""
    item = Software(id='a', name='a', folder=tmp_path, executable=tmp_path / 'my app' / 'setup.exe',
                    args='/D=C:\\Program Files\\App /S')
    command, cwd, codes = runner.command_for(item)
    assert command == f'"{tmp_path / "my app" / "setup.exe"}" /D=C:\\Program Files\\App /S'
    assert cwd == tmp_path and codes == frozenset({0})


def test_command_line_for_task(tmp_path):
    """第 7.3 節：以 cmd.exe 的完整路徑執行，/d 停用 AutoRun；/s 讓含空白的路徑也正確"""
    task = SystemTask(id='t', name='t', description='', script=tmp_path / 'a b' / 't.cmd')
    command, cwd, codes = runner.command_for(task)
    assert command.endswith(f'cmd.exe" /d /s /c ""{task.script}""')
    assert cwd == tmp_path / 'a b' and codes == frozenset({0})


# ========== execute（Windows） ==========

@windows_only
def test_success_and_output(tmp_path):
    result = runner.execute(python_item(tmp_path, "print('hello')"), timeout=30)
    assert (result.status, result.exit_code) == ('success', 0)
    assert 'hello' in result.output and result.duration_s > 0


@windows_only
@pytest.mark.parametrize('code, codes, status', [
    (1, frozenset({0}), 'failed'),
    (3010, frozenset({0, 3010}), 'success'),     # DD2：成功，但需要重新開機
    (3010, frozenset({0}), 'failed'),
], ids=['failed', '3010-allowed', '3010-not-allowed'])
def test_success_codes(tmp_path, code, codes, status):
    result = runner.execute(python_item(tmp_path, f'raise SystemExit({code})', success_codes=codes), timeout=30)
    assert (result.status, result.exit_code) == (status, code)


@windows_only
def test_args_reach_the_program_verbatim(tmp_path):
    """FR-41：參數含 Windows 路徑時，執行檔收到的和設定完全相同"""
    out = tmp_path / 'cmdline.txt'
    code = (f"import ctypes; ctypes.windll.kernel32.GetCommandLineW.restype = ctypes.c_wchar_p; "
            f"open(r'{out}', 'w', encoding='utf-8').write(ctypes.windll.kernel32.GetCommandLineW())")
    item = python_item(tmp_path, code)
    item = Software(**{**item.__dict__, 'args': item.args + ' /D=C:\\Program Files\\App /S'})
    runner.execute(item, timeout=30)
    assert out.read_text(encoding='utf-8').endswith(' /D=C:\\Program Files\\App /S')


@windows_only
def test_working_directory_is_the_item_folder(tmp_path):
    out = tmp_path / 'cwd.txt'
    item = python_item(tmp_path, f"import os; open(r'{out}', 'w').write(os.getcwd())")
    runner.execute(item, timeout=30)
    assert Path(out.read_text()) == item.folder


@windows_only
def test_chinese_output_is_decoded(tmp_path, monkeypatch):
    """FR-45：以 OEM 碼頁解碼，成功的項目不會因為輸出而被判為失敗"""
    monkeypatch.setattr(runner, 'oem_encoding', lambda: 'cp950')
    code = "import sys; sys.stdout.buffer.write('測試'.encode('cp950'))"
    result = runner.execute(python_item(tmp_path, code), timeout=30)
    assert result.status == 'success' and '測試' in result.output


@windows_only
def test_utf8_output_is_decoded(tmp_path, monkeypatch):
    """第 7.5 節：固定輸出 UTF-8 的程式（和真實資料裡 Python 包裝程式相同的寫法），中文也讀得懂"""
    monkeypatch.setattr(runner, 'oem_encoding', lambda: 'cp950')
    code = "import sys; sys.stdout.reconfigure(encoding='utf-8'); print('複製完成'); print('部署完成')"
    result = runner.execute(python_item(tmp_path, code), timeout=30)
    assert result.status == 'success' and result.output.splitlines() == ['複製完成', '部署完成']


@windows_only
def test_timeout_kills_the_whole_process_tree(tmp_path):
    """DD3：逾時時結束整個行程樹，安裝程式啟動的子程式也一起結束"""
    pid_file = tmp_path / 'child.pid'
    code = ("import subprocess, sys, time; "
            "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
            f"open(r'{pid_file}', 'w').write(str(p.pid)); time.sleep(60)")
    started = time.monotonic()
    result = runner.execute(python_item(tmp_path, code), timeout=3)

    assert result.status == 'timeout' and result.exit_code is None
    assert time.monotonic() - started < 20
    assert '3 秒' in result.output
    child = int(pid_file.read_text())
    time.sleep(0.5)
    assert not is_running(child)


@windows_only
def test_leftover_child_holding_the_output_does_not_hang(tmp_path):
    """安裝程式結束了，它啟動的程式還開著輸出管線：不等它，記錄後繼續"""
    pid_file = tmp_path / 'child.pid'
    code = ("import subprocess, sys; "
            "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
            f"open(r'{pid_file}', 'w').write(str(p.pid)); print('installed')")
    started = time.monotonic()
    try:
        result = runner.execute(python_item(tmp_path, code), timeout=60)
        assert time.monotonic() - started < 15
        assert result.status == 'success' and 'installed' in result.output
        assert '仍在執行' in result.output
    finally:
        subprocess.run(['taskkill', '/PID', pid_file.read_text(), '/F'], capture_output=True)


@windows_only
def test_cannot_start(tmp_path):
    item = Software(id='gone', name='gone', folder=tmp_path, executable=tmp_path / 'gone.exe')
    result = runner.execute(item, timeout=30)
    assert result.status == 'error' and result.exit_code is None and result.output


@windows_only
def test_waiting_for_input_does_not_hang(tmp_path):
    """規則 5 被違反時（pause、等待輸入），不會卡到逾時：沒有輸入可讀"""
    task = cmd_task(tmp_path / 'tasks', 'pauses', 'pause\nexit /b 0')
    started = time.monotonic()
    assert runner.execute(task, timeout=30).status == 'success'
    assert time.monotonic() - started < 10


@windows_only
@pytest.mark.parametrize('exit_code, status', [(0, 'success'), (1, 'failed')])
def test_cmd_task(tmp_path, exit_code, status):
    """任務：結束碼 0 為成功，其他都是失敗（第 7.3 節）；路徑含空白也能執行"""
    task = cmd_task(tmp_path / 'with space' / 'tasks', 'power_001', f'echo running\nexit /b {exit_code}')
    result = runner.execute(task, timeout=30)
    assert (result.status, result.exit_code) == (status, exit_code)
    assert 'running' in result.output


# ========== run_batch：三個階段 ==========

@pytest.fixture
def env(tmp_path, monkeypatch):
    """資源資料夾、下載資料夾、桌面（日誌）都在暫存資料夾裡"""
    res = tmp_path / 'helper_software'
    (res / 'a').mkdir(parents=True)
    (res / 'a' / 'setup.exe').write_bytes(b'a')
    (res / 'b').mkdir()
    (res / 'b' / 'setup.exe').write_bytes(b'b')
    downloads = tmp_path / 'Downloads'
    downloads.mkdir()
    desktop = tmp_path / 'Desktop'
    monkeypatch.setattr(paths, 'desktop_dir', lambda: desktop)
    return res, downloads, desktop


def items_in(res, *names, copy_first=True):
    return [Software(id=n, name=n, folder=res / n, executable=res / n / 'setup.exe', copy_first=copy_first)
            for n in names]


class FakeExecute:
    """記下每個項目從哪裡執行；不真的執行程式"""

    def __init__(self, statuses=None):
        self.calls = []
        self.statuses = statuses or {}

    def __call__(self, item, timeout):
        self.calls.append(item)
        status = self.statuses.get(item.id, 'success')
        if status == 'raise':
            raise RuntimeError(f'模擬的非預期錯誤：{item.id}')
        return TaskResult(item.id, status, 0 if status == 'success' else 1, 0.1, f'output of {item.id}')


def run(res, downloads, items, *, fake=None, cancel=None, resume=None, on_progress=None, mode='software',
        problems=()):
    cancel = cancel or threading.Event()
    if resume is None:
        resume = threading.Event()
        resume.set()
    return runner.run_batch(mode, items, resource_dir=res, timeout=30, problems=problems, is_admin=True,
                            cancel=cancel, resume=resume, on_progress=on_progress or (lambda *a: None),
                            downloads=downloads, secure=False)


def log_text(desktop):
    [log] = (desktop / 'QT_TOOL_LOGS').glob('*.log')
    return log.read_text(encoding='utf-8')


def test_batch_copies_runs_from_copies_and_cleans_up(env, monkeypatch):
    res, downloads, desktop = env
    fake = FakeExecute()
    monkeypatch.setattr(runner, 'execute', fake)
    items = items_in(res, 'a', 'b')

    result = run(res, downloads, items)

    assert [r.status for r in result.results] == ['success', 'success']
    assert result.aborted is None
    stage = fake.calls[0].folder.parent
    assert stage.parent == downloads and stage.name.startswith('Helper_')  # 從複本執行（FR-46）
    assert [c.executable for c in fake.calls] == [stage / 'a' / 'setup.exe', stage / 'b' / 'setup.exe']
    assert result.cleanup.removed == (stage,) and list(downloads.iterdir()) == []  # 結束後刪除（FR-48）


def test_items_not_copied_run_in_place(env, monkeypatch):
    res, downloads, _ = env
    fake = FakeExecute()
    monkeypatch.setattr(runner, 'execute', fake)
    items = items_in(res, 'a', copy_first=False)
    run(res, downloads, items)
    assert fake.calls == items


def test_tasks_are_always_copied(env, monkeypatch):
    res, downloads, _ = env
    fake = FakeExecute()
    monkeypatch.setattr(runner, 'execute', fake)
    task = cmd_task(res / 'tasks', 'power_001', 'exit /b 0')
    run(res, downloads, [task], mode='tasks')
    [called] = fake.calls
    assert called.script.parent.name == 'tasks' and called.script.parent.parent.parent == downloads


def test_not_enough_space_runs_nothing(env, monkeypatch):
    """FR-47：空間不夠時不執行任何項目，原因記在 aborted 與日誌"""
    res, downloads, desktop = env
    fake = FakeExecute()
    monkeypatch.setattr(runner, 'execute', fake)
    monkeypatch.setattr(staging, 'check_space', lambda target, needed: '空間不足：模擬')

    result = run(res, downloads, items_in(res, 'a'))

    assert result.aborted == '空間不足：模擬' and result.results == () and fake.calls == []
    assert list(downloads.iterdir()) == []
    assert '沒有執行任何項目：空間不足：模擬' in log_text(desktop)


def test_copy_failure_affects_only_that_item(env, monkeypatch):
    res, downloads, _ = env
    fake = FakeExecute()
    monkeypatch.setattr(runner, 'execute', fake)
    real_copy = staging.copy_software

    def copy(stage, resource_dir, item):
        if item.id == 'a':
            return staging.CopyResult(None, stage / 'a', error='模擬：讀取失敗')
        return real_copy(stage, resource_dir, item)

    monkeypatch.setattr(staging, 'copy_software', copy)
    result = run(res, downloads, items_in(res, 'a', 'b'))

    assert [(r.item_id, r.status) for r in result.results] == [('a', 'copy_failed'), ('b', 'success')]
    assert '模擬：讀取失敗' in result.results[0].output
    assert [c.id for c in fake.calls] == ['b']


def test_staging_cannot_be_created(env, monkeypatch):
    res, downloads, _ = env
    fake = FakeExecute()
    monkeypatch.setattr(runner, 'execute', fake)

    def fail(*args, **kwargs):
        raise OSError('無法設定暫存資料夾的權限')

    monkeypatch.setattr(staging, 'create', fail)
    result = run(res, downloads, items_in(res, 'a'))
    assert '無法設定暫存資料夾的權限' in result.aborted and fake.calls == []


def test_log_cannot_be_created(env, monkeypatch):
    """FR-53：回傳原因，由介面顯示並恢復按鈕；不執行任何項目"""
    res, downloads, desktop = env
    desktop.write_text('')  # 桌面的位置被檔案佔用，日誌資料夾建不出來
    fake = FakeExecute()
    monkeypatch.setattr(runner, 'execute', fake)
    result = run(res, downloads, items_in(res, 'a'))
    assert '日誌' in result.aborted and fake.calls == [] and list(downloads.iterdir()) == []


def test_unexpected_error_in_one_item(env, monkeypatch):
    """設計第 13 節：一個項目出錯，記錄完整的錯誤堆疊，其他項目照常，暫存資料夾照樣刪除"""
    res, downloads, desktop = env
    monkeypatch.setattr(runner, 'execute', FakeExecute({'a': 'raise'}))

    result = run(res, downloads, items_in(res, 'a', 'b'))

    assert [(r.item_id, r.status) for r in result.results] == [('a', 'error'), ('b', 'success')]
    assert 'RuntimeError' in result.results[0].output
    assert 'Traceback' in log_text(desktop)
    assert list(downloads.iterdir()) == []


def test_cancel_stops_before_the_next_item(env, monkeypatch):
    """FR-44：目前項目完成後停止；沒有執行的項目不算成功也不算失敗（FR-51）"""
    res, downloads, desktop = env
    cancel = threading.Event()
    fake = FakeExecute()

    def execute(item, timeout):
        cancel.set()  # 第一個項目執行中按下「取消」
        return fake(item, timeout)

    monkeypatch.setattr(runner, 'execute', execute)
    result = run(res, downloads, items_in(res, 'a', 'b'), cancel=cancel)

    assert [r.item_id for r in result.results] == ['a']
    assert list(downloads.iterdir()) == []  # 取消時也刪除暫存資料夾
    assert '使用者取消' in log_text(desktop)


def test_cancel_during_copy(env, monkeypatch):
    res, downloads, _ = env
    cancel = threading.Event()
    fake = FakeExecute()
    monkeypatch.setattr(runner, 'execute', fake)

    def on_progress(item_id, state, result):
        if state == 'copied':
            cancel.set()

    result = run(res, downloads, items_in(res, 'a', 'b'), cancel=cancel, on_progress=on_progress)
    assert result.results == () and fake.calls == [] and list(downloads.iterdir()) == []


def test_pause_waits_between_items(env, monkeypatch):
    """FR-43：暫停在目前項目完成後生效，按「繼續」後恢復"""
    res, downloads, _ = env
    resume = threading.Event()
    resume.set()
    fake = FakeExecute()

    def execute(item, timeout):
        resume.clear()  # 第一個項目執行中按下「暫停」
        return fake(item, timeout)

    monkeypatch.setattr(runner, 'execute', execute)
    outcome = {}
    worker = threading.Thread(target=lambda: outcome.setdefault('r', run(res, downloads, items_in(res, 'a', 'b'),
                                                                          resume=resume)))
    worker.start()
    time.sleep(0.5)
    assert worker.is_alive() and [c.id for c in fake.calls] == ['a']  # 停在兩個項目之間
    resume.set()
    worker.join(10)
    assert [r.item_id for r in outcome['r'].results] == ['a', 'b']


def test_progress_notifications(env, monkeypatch):
    res, downloads, _ = env
    monkeypatch.setattr(runner, 'execute', FakeExecute())
    events = []
    run(res, downloads, items_in(res, 'a'), on_progress=lambda i, s, r: events.append((i, s, r and r.status)))
    assert events == [('a', 'waiting', None), ('a', 'copying', None), ('a', 'copied', None),
                      ('a', 'running', None), ('a', 'done', 'success')]


def test_log_has_every_section(env, monkeypatch):
    res, downloads, desktop = env
    monkeypatch.setattr(runner, 'execute', FakeExecute({'b': 'failed'}))
    run(res, downloads, items_in(res, 'a', 'b'), problems=[Problem('warning', 'software.xml', 'x', '注意')])
    content = log_text(desktop)
    for expected in ('===== 開始', '===== 問題清單', '[warning] software.xml x：注意', '===== 勾選的項目（2 個）',
                     '===== 複製', '===== 執行', 'output of a', '===== 刪除暫存資料夾', '已刪除：',
                     '===== 結尾', '成功 1、失敗 1'):
        assert expected in content


@windows_only
def test_end_to_end_with_real_processes(env):
    """實際複製、實際執行 .cmd、實際刪除"""
    res, downloads, desktop = env
    tasks = [cmd_task(res / 'tasks', 'ok', 'echo ok\nexit /b 0'), cmd_task(res / 'tasks', 'bad', 'exit /b 2')]
    result = run(res, downloads, tasks, mode='tasks')
    assert [(r.item_id, r.status, r.exit_code) for r in result.results] == [('ok', 'success', 0), ('bad', 'failed', 2)]
    assert list(downloads.iterdir()) == []
    assert 'Helper_系統設定_' in next((desktop / 'QT_TOOL_LOGS').iterdir()).name


def test_runner_never_touches_the_gui():
    """第 7.1 節：runner 不碰介面，只呼叫 on_progress（只有 gui 可以 import tkinter）"""
    source = (Path(runner.__file__)).read_text(encoding='utf-8')
    assert 'tkinter' not in source
