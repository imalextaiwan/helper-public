"""資料模型（設計第 5 節）

純資料，沒有任何邏輯，全部唯讀。介面的勾選狀態不放在這裡，由 gui 以 id 對應
自己的 BooleanVar，所以讀設定與執行時都不需要建立任何 tkinter 物件。
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Severity = Literal['fatal', 'error', 'warning']
Status = Literal['success', 'failed', 'timeout', 'error', 'copy_failed']


@dataclass(frozen=True)
class Software:
    """軟體項目：software.xml 的一個 <item>（設計第 4.2 節）"""
    id: str
    name: str
    folder: Path                    # 絕對路徑
    executable: Path                # 絕對路徑
    args: str = ''                  # 原始字串，不切割，原樣傳給執行檔（第 7.2 節）
    success_codes: frozenset[int] = frozenset({0})   # 視為成功的結束碼（DD2）
    copy_first: bool = True         # 執行前先複製到暫存資料夾（第 7.7 節、DD14）
    icon: Path | None = None        # 子資料夾裡的 icon.*，沒有就是 None（FR-16）


@dataclass(frozen=True)
class SystemTask:
    """系統設定任務：system_tasks.xml 的一個 <task>（設計第 4.3 節）"""
    id: str
    name: str
    description: str
    script: Path                    # 絕對路徑：<資源資料夾>\tasks\<id>.cmd


@dataclass(frozen=True)
class TaskCategory:
    """系統設定的分類，介面上顯示為一個區塊（FR-32）"""
    id: str
    name: str
    tasks: tuple[SystemTask, ...]


@dataclass(frozen=True)
class Problem:
    """問題清單的一筆（FR-20、設計第 6.2 節）"""
    severity: Severity
    file: str                       # 例如 "software.xml"
    item_id: str | None             # 和整個檔案有關的問題是 None
    message: str


@dataclass(frozen=True)
class LoadResult:
    """config.load 讀完兩個 XML 的結果"""
    resource_dir: Path
    software: tuple[Software, ...]
    software_timeout: int           # 秒
    categories: tuple[TaskCategory, ...]
    task_timeout: int               # 秒
    problems: tuple[Problem, ...]


@dataclass(frozen=True)
class TaskResult:
    """一個項目的執行結果（設計第 7.6 節）"""
    item_id: str
    status: Status
    exit_code: int | None           # 沒有啟動或逾時被結束時是 None
    duration_s: float
    output: str                     # 已解碼的 stdout + stderr；失敗時含原因


@dataclass(frozen=True)
class CleanupResult:
    """刪除暫存資料夾的結果（FR-48）"""
    removed: tuple[Path, ...]       # 刪除的暫存資料夾
    leftovers: tuple[str, ...]      # 刪不掉的檔案與原因


@dataclass(frozen=True)
class BatchResult:
    """一輪執行的結果"""
    results: tuple[TaskResult, ...]
    cleanup: CleanupResult
    aborted: str | None = None      # 沒有執行任何項目的原因，例如空間不足（FR-47）
