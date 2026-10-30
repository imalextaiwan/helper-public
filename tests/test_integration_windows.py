"""Windows 整合測試：runner + 真的 cmd.exe（設計第 14 節、T36；FR-42、FR-45）

以 runner.execute 實際執行 .cmd，確認 3.0 執行任務的方式在 Windows 上的行為：
結束碼、CRLF 與標籤、批次檔對 % 的處理（ini2xml 轉換規則的依據）、中文路徑、
大量輸出。逾時結束行程樹、暫存資料夾的權限與目錄連結，分別在 test_runner、
test_staging 以實際的行程與檔案系統測試。
"""
import sys

import pytest

from hpler import runner
from hpler.models import SystemTask

pytestmark = pytest.mark.skipif(sys.platform != 'win32', reason='需要 Windows 的 cmd.exe')


def run_cmd(folder, body, *, encoding='ascii', task_id='task'):
    """把 body 存成 CRLF 的 .cmd，以 runner.execute 執行（和 3.0 執行任務的方式相同）"""
    folder.mkdir(parents=True, exist_ok=True)
    script = folder / f'{task_id}.cmd'
    script.write_bytes(('@echo off\r\n' + body.replace('\n', '\r\n') + '\r\n').encode(encoding))
    return runner.execute(SystemTask(id=task_id, name=task_id, description='', script=script), timeout=60)


def lines(result):
    return [line.strip() for line in result.output.splitlines() if line.strip()]


# ========== 結束碼（撰寫規則 1） ==========

@pytest.mark.parametrize('body, code', [
    ('exit /b 0', 0),
    ('exit /b 7', 7),
    ('cmd /c exit 3 || exit /b 1\nexit /b 0', 1),          # 失敗即停範本
    ('set "FAILED=0"\ncmd /c exit 3 || set "FAILED=1"\necho next\nexit /b %FAILED%', 1),  # 全部跑完範本
], ids=['zero', 'seven', 'stop-on-error', 'run-all'])
def test_exit_codes(tmp_path, body, code):
    result = run_cmd(tmp_path, body)
    assert result.exit_code == code
    assert result.status == ('success' if code == 0 else 'failed')


def test_without_exit_the_last_command_decides(tmp_path):
    """沒有 exit /b 時，結束碼是最後一條指令的結果：這就是規則 1 要求明確結束的原因"""
    assert run_cmd(tmp_path, 'cmd /c exit 4').exit_code == 4
    assert run_cmd(tmp_path, 'cmd /c exit 4\necho done').exit_code == 0  # 失敗被後面的 echo 蓋掉了


# ========== CRLF、標籤（撰寫規則 3） ==========

def test_goto_and_call_labels(tmp_path):
    body = ('call :step one\n'
            'call :step two\n'
            'goto :finish\n'
            'echo skipped\n'
            ':step\n'
            'echo step %~1\n'
            'exit /b 0\n'
            ':finish\n'
            'echo finished\n'
            'exit /b 0')
    result = run_cmd(tmp_path, body)
    assert result.status == 'success'
    assert lines(result) == ['step one', 'step two', 'finished']


# ========== 批次檔對 % 的處理（設計第 11 節的轉換規則） ==========

@pytest.mark.parametrize('body, expected', [
    ('echo 50%%', ['50%']),                                 # 單一 % 在批次檔要寫成 %%
    ('echo %OS%', ['Windows_NT']),                          # %名稱% 是環境變數
    ('echo [%HPLER_UNDEFINED_VAR%]', ['[]']),              # 沒有定義的變數變成空字串（轉換報告要列出）
    ('for %%i in (a b) do echo item %%i', ['item a', 'item b']),   # 迴圈變數要寫成 %%i
    ('setlocal\nset "X=1"\necho %X%', ['1']),
], ids=['percent', 'env-var', 'undefined-var', 'for-loop', 'set-var'])
def test_percent_in_batch_files(tmp_path, body, expected):
    assert lines(run_cmd(tmp_path, body + '\nexit /b 0')) == expected


def test_single_percent_is_eaten_in_batch_files(tmp_path):
    """命令列模式的 50% 搬進批次檔會變成 50：所以轉換工具要改成 %%"""
    assert lines(run_cmd(tmp_path, 'echo 50%\nexit /b 0')) == ['50']


# ========== 路徑與輸出 ==========

def test_chinese_folder_name(tmp_path):
    """使用者資料夾或資源資料夾含中文時也能執行"""
    result = run_cmd(tmp_path / '中文資料夾' / 'tasks', 'echo ok\nexit /b 0')
    assert result.status == 'success' and lines(result) == ['ok']


def test_working_directory_is_the_tasks_folder(tmp_path):
    result = run_cmd(tmp_path / 'stage' / 'tasks', 'cd\nexit /b 0')
    assert lines(result) == [str(tmp_path / 'stage' / 'tasks')]


def test_large_output_does_not_block(tmp_path):
    """輸出遠大於管線的緩衝區（約 1 MB）時不會卡住，而且完整保留（DD17）"""
    result = run_cmd(tmp_path, 'for /l %%i in (1,1,20000) do echo line %%i of the very long output 0123456789\n'
                               'exit /b 0')
    assert result.status == 'success'
    assert lines(result)[0] == 'line 1 of the very long output 0123456789'
    assert lines(result)[-1] == 'line 20000 of the very long output 0123456789'


def test_stderr_is_kept(tmp_path):
    result = run_cmd(tmp_path, 'echo to stdout\necho to stderr 1>&2\nexit /b 0')
    assert lines(result) == ['to stdout', 'to stderr']


def test_ansi_script_with_chinese_echo(tmp_path, monkeypatch):
    """規則 2：.cmd 存成 ANSI（Big5）時，cmd.exe 原樣輸出這些位元組；以 cp950 解碼就是中文。
    （這台電腦的 OEM 碼頁不是 950 時，這裡固定以 cp950 解碼來模擬繁中 Windows）"""
    if runner.oem_encoding() == 'cp65001':
        pytest.skip('OEM 碼頁為 65001 時，cmd.exe 不會原樣輸出 cp950 位元組')
    monkeypatch.setattr(runner, 'oem_encoding', lambda: 'cp950')
    result = run_cmd(tmp_path, 'echo 中文訊息\nexit /b 0', encoding='cp950')
    assert result.status == 'success'
    assert lines(result) == ['中文訊息']


def test_cp950_and_utf8_output_in_one_script(tmp_path, monkeypatch):
    """設計第 7.5 節：同一個 .cmd 先以系統碼頁輸出中文，再 chcp 65001 以 UTF-8 輸出
    （例如之後呼叫固定輸出 UTF-8 的 Python 工具）→ 兩段都讀得懂。
    chcp 之後，cmd.exe 以 UTF-8 讀取後面的指令，也以 UTF-8 輸出"""
    if runner.oem_encoding() == 'cp65001':
        pytest.skip('OEM 碼頁為 65001 時，cmd.exe 不會原樣輸出 cp950 位元組')
    monkeypatch.setattr(runner, 'oem_encoding', lambda: 'cp950')
    script = tmp_path / 'task.cmd'
    script.write_bytes(b'@echo off\r\n' + 'echo 中文訊息\r\n'.encode('cp950') + b'chcp 65001 >nul\r\n'
                       + 'echo UTF-8 的中文\r\n'.encode('utf-8') + b'exit /b 0\r\n')
    result = runner.execute(SystemTask(id='task', name='task', description='', script=script), timeout=60)
    assert result.status == 'success'
    assert lines(result) == ['中文訊息', 'UTF-8 的中文']
