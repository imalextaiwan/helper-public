"""3.0 的完整日誌（設計第 8 節；FR-50、FR-52～FR-54）

每輪一個日誌檔，依時間順序寫入各區段；輸出不截斷；每一筆寫入後立刻存檔，
工具異常結束時日誌仍保留到最後一刻。
"""
import logging
import os
from datetime import datetime
from pathlib import Path

import pytest

import hpler
from hpler import logs, paths
from hpler.models import CleanupResult, Problem, Software, SystemTask, TaskResult

REPO = Path(__file__).resolve().parent.parent
RES = Path(r'C:\res')
CPU_Z = Software(id='cpu_z', name='CPU-Z', folder=RES / 'cpu-z', executable=RES / 'cpu-z' / 'setup.exe')
DESK = Software(id='desk', name='SampleDeskTool', folder=RES / 'desk', executable=RES / 'desk' / 'd.exe',
                copy_first=False)
TASK = SystemTask(id='power_001', name='高效能電源', description='', script=RES / 'tasks' / 'power_001.cmd')


@pytest.fixture
def desktop(tmp_path, monkeypatch):
    """日誌寫在 <桌面>\\QT_TOOL_LOGS；桌面改到暫存資料夾"""
    monkeypatch.setattr(paths, 'desktop_dir', lambda: tmp_path)
    return tmp_path


def text(log):
    return log.path.read_text(encoding='utf-8')


def result(item_id, status, exit_code=0, output=''):
    return TaskResult(item_id=item_id, status=status, exit_code=exit_code, duration_s=1.25, output=output)


# ========== 檔案 ==========

def test_log_file_location_and_name(desktop):
    with logs.open_run_log('software') as log:
        assert log.path.parent == desktop / 'QT_TOOL_LOGS'
        assert log.path.name.startswith('Helper_軟體安裝_') and log.path.suffix == '.log'
        datetime.strptime(log.path.stem.removeprefix('Helper_軟體安裝_'), '%Y%m%d_%H%M%S')
    with logs.open_run_log('tasks') as log:
        assert log.path.name.startswith('Helper_系統設定_')


def test_log_folder_is_the_one_the_button_opens(desktop):
    """FR-52：「日誌資料夾」按鈕開啟的就是寫入的資料夾"""
    with logs.open_run_log('software') as log:
        assert log.path.parent == logs.log_dir()


def test_each_run_gets_its_own_file_even_in_the_same_second(desktop, monkeypatch):
    class FrozenClock:
        @staticmethod
        def now():
            return datetime(2026, 10, 22, 10, 0, 0)

    monkeypatch.setattr(logs, 'datetime', FrozenClock)
    with logs.open_run_log('software') as first, logs.open_run_log('software') as second:
        first.aborted('第一輪')
        second.aborted('第二輪')
    assert first.path != second.path
    assert '第一輪' in text(first) and '第二輪' not in text(first)
    assert '第二輪' in text(second)


def test_written_immediately(desktop):
    """還沒關閉前，內容就已經在檔案裡（工具異常結束時日誌保留到最後一刻）"""
    log = logs.open_run_log('software')
    try:
        log.aborted('寫入後立刻存檔')
        assert '寫入後立刻存檔' in text(log)
    finally:
        log.close()


def test_file_is_closed(desktop):
    with logs.open_run_log('software') as log:
        log.aborted('x')
    os.remove(log.path)  # Windows 上檔案還開著就刪不掉


def test_root_logger_is_left_alone(desktop):
    before = list(logging.getLogger().handlers)
    with logs.open_run_log('software') as log:
        log.aborted('x')
    assert logging.getLogger().handlers == before


def test_log_folder_cannot_be_created(desktop):
    """FR-53：建立失敗時拋出 OSError，由呼叫端顯示原因並恢復按鈕"""
    (desktop / 'QT_TOOL_LOGS').write_text('')  # 同名的檔案擋住
    with pytest.raises(OSError):
        logs.open_run_log('software')


# ========== 各區段（FR-54） ==========

def test_header(desktop):
    with logs.open_run_log('software') as log:
        log.header(resource_dir=RES, staging_dir=Path(r'C:\Users\x\Downloads\Helper_20261022_100000'),
                   timeout=1000, is_admin=True)
    content = text(log)
    for expected in (f'Helper {hpler.__version__}', '軟體安裝', os.environ.get('COMPUTERNAME', ''),
                     'Windows', '系統管理員：是', str(RES), 'Helper_20261022_100000', '1000 秒'):
        assert expected in content


def test_header_without_staging(desktop):
    with logs.open_run_log('software') as log:
        log.header(resource_dir=RES, staging_dir=None, timeout=300, is_admin=False)
    assert '暫存資料夾：（不使用）' in text(log)
    assert '系統管理員：否' in text(log)


def test_problems(desktop):
    with logs.open_run_log('software') as log:
        log.problems([])
        log.problems([Problem('error', 'software.xml', 'vcredist', 'successCodes 格式錯誤'),
                      Problem('warning', 'tasks\\old.cmd', None, '沒有登記')])
    content = text(log)
    assert '===== 問題清單 =====' in content and '無' in content
    assert '[error] software.xml vcredist：successCodes 格式錯誤' in content
    assert '[warning] tasks\\old.cmd -：沒有登記' in content


def test_selected_items(desktop):
    with logs.open_run_log('software') as log:
        log.selected([CPU_Z, DESK, TASK])
    content = text(log)
    assert '勾選的項目（3 個）' in content
    assert '1. cpu_z　CPU-Z　先複製' in content
    assert '2. desk　SampleDeskTool　不先複製' in content
    assert '3. power_001　高效能電源　先複製' in content  # 任務一律先複製（DD16）


def test_copy(desktop):
    with logs.open_run_log('software') as log:
        log.section('複製')
        log.copied('cpu_z', RES / 'cpu-z', Path(r'D:\stage\cpu-z'), files=12, size_bytes=5 * 1024 * 1024,
                   seconds=2.5)
        log.copy_failed('vcredist', RES / 'VCRedist', Path(r'D:\stage\VCRedist'), '磁碟已滿',
                        failed_files=['VCRedist\\vc_redist.x64.exe'])
    content = text(log)
    assert 'cpu_z：C:\\res\\cpu-z → D:\\stage\\cpu-z（12 個檔案，5.0 MB，2.5 秒）' in content
    assert 'ERROR' in content and 'vcredist：複製失敗' in content and '磁碟已滿' in content
    assert 'VCRedist\\vc_redist.x64.exe' in content


def test_run(desktop):
    output = '第一行\r\n第二行\r\n'
    with logs.open_run_log('software') as log:
        log.run_started(1, 2, CPU_Z, '"C:\\res\\cpu-z\\setup.exe" /S', RES / 'cpu-z')
        log.run_finished(result('cpu_z', 'success', 0, output))
        log.run_finished(result('vcredist', 'timeout', None))
    content = text(log)
    assert '[1/2] cpu_z　CPU-Z' in content
    assert '命令列："C:\\res\\cpu-z\\setup.exe" /S' in content
    assert '工作目錄：C:\\res\\cpu-z' in content
    assert '結果：成功（結束碼 0，1.2 秒）' in content or '結果：成功（結束碼 0，1.3 秒）' in content
    assert '第一行\n' in content and '第二行' in content
    assert b'\r\r' not in log.path.read_bytes()  # 輸出裡的 \r\n 不會變成 \r\r\n
    assert '結果：逾時（結束碼 -，' in content


def test_output_is_not_truncated(desktop):
    """DD17：完整輸出，不截斷（2.0 最多保留 4,000 字元）"""
    output = '\n'.join(f'第 {i} 行的輸出' for i in range(3000))  # 約 3 萬字元
    with logs.open_run_log('tasks') as log:
        log.run_finished(result('t', 'failed', 1, output))
    assert '第 0 行的輸出' in text(log) and '第 2999 行的輸出' in text(log)


def test_cleanup(desktop):
    with logs.open_run_log('software') as log:
        log.cleanup(CleanupResult(removed=(Path(r'D:\stage'),), leftovers=('D:\\stage\\a.exe：使用中',)))
        log.cleanup(CleanupResult(removed=(), leftovers=()))
    content = text(log)
    assert '已刪除：D:\\stage' in content
    assert '刪不掉：D:\\stage\\a.exe：使用中' in content
    assert '沒有要刪除的暫存資料夾' in content


def test_summary(desktop):
    results = [result('a', 'success'), result('b', 'success'), result('c', 'failed', 1),
               result('d', 'timeout', None), result('e', 'error', None), result('f', 'copy_failed', None)]
    with logs.open_run_log('software') as log:
        log.summary(results)
    content = text(log)
    assert '成功 2、失敗 1、逾時 1、無法啟動 1、複製失敗 1' in content
    for line in ('c：失敗', 'd：逾時', 'e：無法啟動', 'f：複製失敗'):
        assert line in content
    assert 'a：成功' not in content
    assert '總耗時' in content


def test_cancelled(desktop):
    with logs.open_run_log('software') as log:
        log.cancelled()
    assert 'WARNING' in text(log) and '使用者取消' in text(log)


def test_aborted(desktop):
    with logs.open_run_log('software') as log:
        log.aborted('空間不足：需要 19.2 GB，可用 3.0 GB')
    assert 'ERROR' in text(log) and '沒有執行任何項目：空間不足' in text(log)


def test_unexpected_error_writes_traceback(desktop):
    with logs.open_run_log('software') as log:
        try:
            raise RuntimeError('模擬的非預期錯誤')
        except RuntimeError:
            log.exception('執行過程發生錯誤')
    content = text(log)
    assert '執行過程發生錯誤' in content and 'Traceback' in content and 'RuntimeError: 模擬的非預期錯誤' in content


def test_sections_in_order(desktop):
    with logs.open_run_log('software') as log:
        log.header(resource_dir=RES, staging_dir=None, timeout=300, is_admin=True)
        log.problems([])
        log.selected([CPU_Z])
        log.section('複製')
        log.section('執行')
        log.cleanup(CleanupResult(removed=(), leftovers=()))
        log.summary([result('cpu_z', 'success')])
    content = text(log)
    titles = ['開始', '問題清單', '勾選的項目', '複製', '執行', '刪除暫存資料夾', '結尾']
    positions = [content.index(f'===== {t}') for t in titles]
    assert positions == sorted(positions)
