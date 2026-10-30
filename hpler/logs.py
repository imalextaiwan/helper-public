"""每輪執行的完整日誌（設計第 8 節；FR-50、FR-52～FR-54）

每輪建立一個專屬的日誌檔：<桌面>\\QT_TOOL_LOGS\\Helper_<模式>_<YYYYMMDD_HHMMSS>.log。
內容依時間順序分成幾個區段：開始、問題清單、勾選的項目、複製、執行、刪除暫存資料夾、
結尾；非預期錯誤發生時立刻寫入完整的錯誤堆疊。每一筆寫入後立刻存檔，工具異常
結束時，日誌仍保留到最後一刻的內容。
"""
from __future__ import annotations

import getpass
import logging
import platform
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Literal, Sequence

from . import PRODUCT_NAME, __version__, paths

if TYPE_CHECKING:  # 只用於型別標註：執行時 logs 只依賴 paths（設計第 2.1 節）
    from .models import CleanupResult, Problem, Software, SystemTask, TaskResult

LOG_DIR_NAME = 'QT_TOOL_LOGS'
Mode = Literal['software', 'tasks']
MODE_NAMES = {'software': '軟體安裝', 'tasks': '系統設定'}
STATUS_NAMES = {'success': '成功', 'failed': '失敗', 'timeout': '逾時',
                'error': '無法啟動', 'copy_failed': '複製失敗'}  # 設計第 7.6 節


def log_dir() -> Path:
    """日誌資料夾：執行時寫入、「日誌資料夾」按鈕開啟的都是這裡（FR-52）"""
    return paths.desktop_dir() / LOG_DIR_NAME


def open_run_log(mode: Mode) -> RunLog:
    """建立這一輪的日誌檔。

    資料夾或檔案建立失敗時拋出 OSError：呼叫端要顯示原因並恢復按鈕（FR-53）。
    同一秒內再執行一輪時，檔名加上 _2、_3，不寫進同一個檔案。
    """
    directory = log_dir()
    directory.mkdir(parents=True, exist_ok=True)
    base = f'{PRODUCT_NAME}_{MODE_NAMES[mode]}_{datetime.now():%Y%m%d_%H%M%S}'
    path = directory / f'{base}.log'
    n = 2
    while path.exists():
        path = directory / f'{base}_{n}.log'
        n += 1

    # 直接建立 Logger，不經過 logging.getLogger：不註冊到全域，也不傳給 root logger。
    # 2.0 用 logging.basicConfig，同一次開啟的第二輪起都寫進第一輪的檔案
    logger = logging.Logger('hpler.run', logging.INFO)
    handler = logging.FileHandler(path, encoding='utf-8')  # 每一筆寫入後立刻 flush
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)-7s %(message)s'))
    logger.addHandler(handler)
    return RunLog(path, logger, mode)


class RunLog:
    """一輪執行的日誌。以 with 使用，結束時關閉檔案；也可以自己呼叫 close。"""

    def __init__(self, path: Path, logger: logging.Logger, mode: Mode):
        self.path = path
        self._logger = logger
        self._mode = mode
        self._started = time.monotonic()

    def __enter__(self) -> RunLog:
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def close(self) -> None:
        for handler in list(self._logger.handlers):
            handler.close()
            self._logger.removeHandler(handler)

    # ---------- 區段 ----------

    def section(self, title: str) -> None:
        self._logger.info(f'===== {title} =====')

    def header(self, *, resource_dir: Path, staging_dir: Path | None, timeout: int, is_admin: bool) -> None:
        """開始：執行環境與這一輪的設定。是否為系統管理員由呼叫端提供（Windows API 集中在 admin）"""
        self.section('開始')
        for label, value in (
            ('工具', f'{PRODUCT_NAME} {__version__}'),
            ('模式', MODE_NAMES[self._mode]),
            ('電腦名稱', platform.node()),
            ('Windows', f'{platform.platform()}（{platform.win32_edition() or "?"}）'),
            ('使用者', getpass.getuser()),
            ('系統管理員', '是' if is_admin else '否'),
            ('資源資料夾', resource_dir),
            ('暫存資料夾', staging_dir or '（不使用）'),
            ('逾時', f'每個項目 {timeout} 秒'),
        ):
            self._logger.info(f'{label}：{value}')

    def problems(self, problems: Sequence[Problem]) -> None:
        """啟動時的問題清單（FR-20）"""
        self.section('問題清單')
        if not problems:
            self._logger.info('無')
        for p in problems:
            self._logger.info(f'[{p.severity}] {p.file} {p.item_id or "-"}：{p.message}')

    def selected(self, items: Sequence[Software | SystemTask]) -> None:
        """依執行順序列出勾選的項目。系統設定任務一律先複製（DD16）"""
        self.section(f'勾選的項目（{len(items)} 個）')
        for i, item in enumerate(items, 1):
            copy = '先複製' if getattr(item, 'copy_first', True) else '不先複製'
            self._logger.info(f'{i}. {item.id}　{item.name}　{copy}')

    def copied(self, item_id: str, source: Path, destination: Path, *,
               files: int, size_bytes: int, seconds: float) -> None:
        self._logger.info(f'{item_id}：{source} → {destination}'
                          f'（{files} 個檔案，{_size(size_bytes)}，{seconds:.1f} 秒）')

    def copy_failed(self, item_id: str, source: Path, destination: Path, reason: str,
                    failed_files: Iterable[str] = ()) -> None:
        self._logger.error(f'{item_id}：複製失敗 {source} → {destination}：{reason}')
        for name in failed_files:
            self._logger.error(f'    {name}')

    def run_started(self, index: int, total: int, item: Software | SystemTask,
                    command_line: str, cwd: Path) -> None:
        """執行前就寫入：工具在執行中異常結束時，日誌看得出停在哪一個項目"""
        self._logger.info(f'[{index}/{total}] {item.id}　{item.name}')
        self._logger.info(f'    命令列：{command_line}')
        self._logger.info(f'    工作目錄：{cwd}')

    def run_finished(self, result: TaskResult) -> None:
        level = logging.INFO if result.status == 'success' else logging.ERROR
        code = '-' if result.exit_code is None else result.exit_code
        self._logger.log(level, f'    結果：{STATUS_NAMES[result.status]}'
                                f'（結束碼 {code}，{result.duration_s:.1f} 秒）')
        if result.output:
            # 完整輸出，不截斷（DD17）。換行統一為 \n：寫入時才換成 Windows 的換行，不會變成兩個 \r
            output = result.output.replace('\r\n', '\n').replace('\r', '\n').rstrip('\n')
            self._logger.info('    輸出：\n' + '\n'.join(f'    | {line}' for line in output.split('\n')))

    def cleanup(self, result: CleanupResult) -> None:
        """刪除暫存資料夾的結果；刪不掉的檔案不可靜默略過（FR-48）"""
        self.section('刪除暫存資料夾')
        if not result.removed:
            self._logger.info('沒有要刪除的暫存資料夾')
        for path in result.removed:
            self._logger.info(f'已刪除：{path}')
        for leftover in result.leftovers:
            self._logger.warning(f'刪不掉：{leftover}')

    def summary(self, results: Sequence[TaskResult]) -> None:
        """結尾：各種結果的數量、沒有成功的項目、總耗時"""
        self.section('結尾')
        counts = Counter(r.status for r in results)
        self._logger.info('、'.join(f'{name} {counts[status]}' for status, name in STATUS_NAMES.items()))
        not_ok = [r for r in results if r.status != 'success']
        if not_ok:
            self._logger.info('沒有成功的項目：')
            for r in not_ok:
                self._logger.info(f'    {r.item_id}：{STATUS_NAMES[r.status]}')
        self._logger.info(f'總耗時：{_duration(time.monotonic() - self._started)}')

    def cancelled(self) -> None:
        """使用者按了「取消」：目前的項目完成後停止（FR-44）"""
        self._logger.warning('使用者取消：目前的項目完成後停止，剩下的項目不執行')

    def aborted(self, reason: str) -> None:
        """沒有執行任何項目，例如空間不足（FR-47）"""
        self._logger.error(f'沒有執行任何項目：{reason}')

    def exception(self, message: str) -> None:
        """在 except 區塊裡呼叫：寫入訊息與完整的錯誤堆疊（設計第 13 節）"""
        self._logger.exception(message)


def _size(size_bytes: int) -> str:
    if size_bytes >= 1024 ** 3:
        return f'{size_bytes / 1024 ** 3:.1f} GB'
    if size_bytes >= 1024 ** 2:
        return f'{size_bytes / 1024 ** 2:.1f} MB'
    return f'{size_bytes / 1024:.1f} KB'


def _duration(seconds: float) -> str:
    if seconds < 60:
        return f'{seconds:.1f} 秒'
    minutes, seconds = divmod(round(seconds), 60)
    return f'{minutes} 分 {seconds} 秒'
