"""執行（設計第 7 節；FR-40～FR-48、FR-51、FR-54）

run_batch 在背景執行緒執行一輪，分三個階段：
1. 複製：空間檢查，逐項複製到暫存資料夾（第 7.7 節）
2. 執行：依序執行每個項目（第 7.2～7.6 節）
3. 刪除：刪除暫存資料夾（finally：完成、取消、例外都會執行）

runner 不碰介面，只呼叫 on_progress(item_id, 狀態, 結果)；介面在主執行緒更新畫面（第 7.1 節）。
取消與暫停只在兩個項目之間檢查，正在執行的項目不會被中斷（Q2）。
"""
from __future__ import annotations

import codecs
import ctypes
import os
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Callable, Sequence

from . import logs, paths, staging
from .models import BatchResult, CleanupResult, Problem, Software, SystemTask, TaskResult

Item = Software | SystemTask
Progress = Callable[[str, str, TaskResult | None], None]
# 狀態：waiting、copying、copied、copy_failed、running、done（後兩者以外的 result 是 None）

CREATE_NO_WINDOW = 0x08000000      # 不為主控台程式另開視窗；輸出已經導向日誌
OUTPUT_GRACE_SECONDS = 5           # 項目結束後，最多再等多久讀完輸出
_SYSTEM32 = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32'


# ========== 輸出解碼（第 7.5 節） ==========

def oem_encoding() -> str:
    """系統的 OEM 碼頁（繁中 Windows 是 cp950；開啟 UTF-8 全球語言支援時是 cp65001）"""
    try:
        name = f'cp{ctypes.windll.kernel32.GetOEMCP()}'
        codecs.lookup(name)
        return name
    except (AttributeError, LookupError):  # 非 Windows（測試環境），或 Python 不認得的碼頁
        return 'utf-8'


def decode_output(data: bytes) -> str:
    """逐行解碼（DD12）：合法的 UTF-8 用 UTF-8，其他行以 OEM 碼頁解碼，無法解碼的位元組
    以 U+FFFD 取代，所以一定不會失敗。

    cmd.exe 以 OEM 碼頁輸出，以 Python 等撰寫的工具常固定輸出 UTF-8，同一份輸出裡可能兩種
    都有，所以逐行判斷；cp950 的中文幾乎不會剛好是合法的 UTF-8。\\r、\\n 不會出現在 UTF-8
    或 cp950 的多位元組字元裡，以它們分行不會切開一個字；換行字元原樣保留。
    """
    if not data:
        return ''
    encoding = oem_encoding()
    return ''.join(_decode_line(line, encoding) for line in data.splitlines(keepends=True))


def _decode_line(line: bytes, encoding: str) -> str:
    try:
        return line.decode('utf-8')
    except UnicodeDecodeError:
        return line.decode(encoding, errors='replace')


# ========== 執行一個項目 ==========

def command_for(item: Item) -> tuple[str, Path, frozenset[int]]:
    """回傳 (命令列, 工作目錄, 成功代碼)。

    軟體項目：執行檔加上引號，參數原樣接在後面，不切割（第 7.2 節、DD5）。
    任務：以 cmd.exe 的完整路徑執行（避免執行到其他位置的同名檔案），/d 停用 AutoRun；
    /s 加上兩層引號，路徑含空白（例如使用者名稱有空白）時也正確（第 7.3 節）。
    """
    if isinstance(item, SystemTask):
        return f'"{_SYSTEM32 / "cmd.exe"}" /d /s /c ""{item.script}""', item.script.parent, frozenset({0})
    command = subprocess.list2cmdline([str(item.executable)])
    if item.args:
        command += ' ' + item.args
    return command, item.folder, item.success_codes


def execute(item: Item, timeout: int) -> TaskResult:
    """執行一個項目，等到結束或逾時。

    - 結束碼屬於成功代碼為 success，否則 failed；無法啟動為 error
    - 逾時時結束整個行程樹（DD3），結果為 timeout
    - 輸出以背景執行緒讀取：安裝程式結束後，它啟動的程式可能還開著輸出管線，
      不能無限期等下去，最多再等 OUTPUT_GRACE_SECONDS 秒
    - 沒有可讀的輸入：等待輸入的指令（例如 pause）會立刻結束，不會卡到逾時
    """
    command, cwd, success_codes = command_for(item)
    started = time.monotonic()
    try:
        process = subprocess.Popen(command, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT,
                                   creationflags=CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
    except OSError as e:
        return TaskResult(item.id, 'error', None, time.monotonic() - started,
                          f'無法啟動：{type(e).__name__}: {e}')

    chunks: list[bytes] = []
    reader = threading.Thread(target=_read_all, args=(process.stdout, chunks), daemon=True)
    reader.start()
    notes = []
    try:
        exit_code = process.wait(timeout=timeout)
        status = 'success' if exit_code in success_codes else 'failed'
    except subprocess.TimeoutExpired:
        _kill_tree(process)
        exit_code, status = None, 'timeout'
        notes.append(f'超過逾時 {timeout} 秒，已結束這個項目與它啟動的所有程式')
    reader.join(OUTPUT_GRACE_SECONDS)
    if reader.is_alive():
        notes.append('它啟動的其他程式仍在執行，之後的輸出沒有記錄')

    output = decode_output(b''.join(list(chunks))).rstrip()
    if notes:
        output = '\n'.join(filter(None, [output] + [f'（{note}）' for note in notes]))
    return TaskResult(item.id, status, exit_code, time.monotonic() - started, output)


def _read_all(stream, chunks: list[bytes]) -> None:
    """一段一段讀：即使最後讀不到結尾，已經讀到的輸出也保留著"""
    while True:
        data = stream.read1(65536)
        if not data:
            break
        chunks.append(data)


def _kill_tree(process: subprocess.Popen) -> None:
    """以 taskkill /T /F 結束整個行程樹：只結束安裝程式本身不夠，它常常會再啟動
    子程式（例如 msiexec），留著的話下一個安裝可能失敗（DD3）"""
    subprocess.run([str(_SYSTEM32 / 'taskkill.exe'), '/PID', str(process.pid), '/T', '/F'],
                   capture_output=True, creationflags=CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


# ========== 一輪執行 ==========

def run_batch(mode: logs.Mode, items: Sequence[Item], *, resource_dir: Path, timeout: int,
              problems: Sequence[Problem] = (), is_admin: bool,
              cancel: threading.Event, resume: threading.Event, on_progress: Progress = lambda *a: None,
              downloads: Path | None = None, secure: bool = True) -> BatchResult:
    """執行一輪。cancel 設定後，在兩個項目之間停止；resume 清除時暫停，設定後繼續。
    取消時也要設定 resume，暫停中的等待才會結束。

    日誌建立失敗、暫存資料夾無法建立、空間不足時，不執行任何項目，原因在
    BatchResult.aborted（介面顯示原因並恢復按鈕，FR-47、FR-53）。
    secure=False 只給測試用（見 staging.create）。
    """
    try:
        log = logs.open_run_log(mode)
    except OSError as e:
        return BatchResult((), CleanupResult((), ()),
                           aborted=f'無法建立日誌檔，沒有執行任何項目：{logs.log_dir()}（{type(e).__name__}: {e}）')

    downloads = downloads or paths.downloads_dir()
    order = {item.id: i for i, item in enumerate(items)}
    results: list[TaskResult] = []
    stage, aborted = None, None
    cleanup = CleanupResult((), ())
    with log:
        try:
            for item in items:
                on_progress(item.id, 'waiting', None)
            to_copy = [item for item in items if _copies(item)]
            if to_copy:
                try:
                    downloads.mkdir(parents=True, exist_ok=True)
                    stage = staging.create(downloads, secure=secure)
                except OSError as e:
                    aborted = f'無法建立暫存資料夾：{e}'
            log.header(resource_dir=resource_dir, staging_dir=stage, timeout=timeout, is_admin=is_admin)
            log.problems(problems)
            log.selected(items)
            if aborted is None and to_copy:
                aborted = staging.check_space(downloads, staging.required_bytes(to_copy))
            if aborted:
                log.aborted(aborted)
            else:
                to_run = _copy_phase(items, stage, resource_dir, log, results, cancel, resume, on_progress)
                if to_run is not None:
                    _run_phase(to_run, timeout, log, results, cancel, resume, on_progress)
        except Exception:  # 邊界：項目以外的非預期錯誤，記錄後交給介面處理（設計第 13 節）
            log.exception('執行過程發生非預期的錯誤')
            raise
        finally:
            try:
                cleanup = staging.cleanup(downloads, stage, resource_dir)
            except Exception:  # 邊界：刪除失敗不可以讓日誌少了結尾
                log.exception('刪除暫存資料夾時發生非預期的錯誤')
                cleanup = CleanupResult((), (f'{stage or downloads}：刪除時發生非預期的錯誤，詳見日誌',))
            log.cleanup(cleanup)
            results.sort(key=lambda r: order.get(r.item_id, len(order)))
            log.summary(results)
    return BatchResult(tuple(results), cleanup, aborted)


def _copies(item: Item) -> bool:
    """任務一律先複製（DD16）；軟體項目看 copyFirst（DD14）"""
    return isinstance(item, SystemTask) or item.copy_first


def _wait_turn(cancel: threading.Event, resume: threading.Event) -> bool:
    """兩個項目之間：暫停中就等，取消了就回傳 False"""
    while not resume.wait(0.2):
        if cancel.is_set():
            return False
    return not cancel.is_set()


def _copy_phase(items, stage, resource_dir, log, results, cancel, resume, on_progress):
    """複製需要先複製的項目，回傳要執行的項目（複本或原本的）；取消時回傳 None"""
    if stage is not None:
        log.section('複製')
    to_run = []
    for item in items:
        if not _wait_turn(cancel, resume):
            log.cancelled()
            return None
        if not _copies(item):
            to_run.append(item)
            continue
        on_progress(item.id, 'copying', None)
        try:
            if isinstance(item, Software):
                copy = staging.copy_software(stage, resource_dir, item)
            else:
                copy = staging.copy_script(stage, item)
        except Exception:  # 邊界：一個項目出錯，不影響其他項目
            log.exception(f'{item.id}：複製時發生非預期的錯誤')
            copy = staging.CopyResult(None, stage, error=traceback.format_exc())
        source = item.folder if isinstance(item, Software) else item.script
        if copy.error is not None:
            result = TaskResult(item.id, 'copy_failed', None, copy.seconds, f'複製失敗：{copy.error}')
            log.copy_failed(item.id, source, copy.destination, copy.error, copy.failed_files)
            results.append(result)
            on_progress(item.id, 'copy_failed', result)
            continue
        log.copied(item.id, source, copy.destination, files=copy.files, size_bytes=copy.size_bytes,
                   seconds=copy.seconds)
        on_progress(item.id, 'copied', None)
        to_run.append(copy.item)
    return to_run


def _run_phase(to_run, timeout, log, results, cancel, resume, on_progress):
    log.section('執行')
    for index, item in enumerate(to_run, 1):
        if not _wait_turn(cancel, resume):
            log.cancelled()
            return
        command, cwd, _codes = command_for(item)
        log.run_started(index, len(to_run), item, command, cwd)
        on_progress(item.id, 'running', None)
        try:
            result = execute(item, timeout)
        except Exception:  # 邊界：一個項目出錯，不影響其他項目
            log.exception(f'{item.id}：執行時發生非預期的錯誤')
            result = TaskResult(item.id, 'error', None, 0.0, traceback.format_exc())
        log.run_finished(result)
        results.append(result)
        on_progress(item.id, 'done', result)
