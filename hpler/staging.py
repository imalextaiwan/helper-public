"""執行時的暫存資料夾（設計第 7.7 節；FR-46～FR-48、NFR-07）

執行前把軟體子資料夾與勾選的 .cmd 複製到「下載」底下這一輪專屬的暫存資料夾
<下載>\\Helper_<YYYYMMDD_HHMMSS>\\，從複本執行，全部結束後刪除。

工具以管理員權限執行，刪錯會造成無法復原的損失：只刪除符合 is_safe_to_delete
四個條件的資料夾。下載資料夾一般使用者可以寫入，所以暫存資料夾建立後立刻改為
只有系統管理員與 SYSTEM 可以寫入，避免在執行前被替換安裝檔。
"""
from __future__ import annotations

import os
import shutil
import stat
import time
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Sequence

from . import PRODUCT_NAME, __version__
from .models import CleanupResult, Software, SystemTask

PREFIX = f'{PRODUCT_NAME}_'
MARKER = '.helper_staging'          # 只有帶這個標記檔的資料夾會被刪除
# (名稱開頭, 標記檔)，兩者必須是同一組。第二組是 3.0.0、3.0.1 建立的（產品名稱誤寫為 Hpler），
# 清除殘留時也要認得，否則會一直留在「下載」裡；3.x 一直保留（設計第 2.4、7.7 節）
STAGE_NAMES = ((PREFIX, MARKER), ('Hpler_', '.hpler_staging'))
MARGIN_BYTES = 1024 ** 3            # 空間檢查的餘裕：1 GB
TASKS_DIR = 'tasks'
# 擁有者是 Administrators；只有 Administrators 與 SYSTEM 完整控制，禁止繼承（設計第 7.7 節）。
# 以 SID 的代號表示，不受系統語系影響
_ADMIN_ONLY = 'O:BAD:P(A;OICI;FA;;;BA)(A;OICI;FA;;;SY)'
_INHERIT_ONLY = 'D:'  # 沒有自己的權限，只從資料夾繼承


@dataclass(frozen=True)
class CopyResult:
    """複製一個項目的結果"""
    item: Software | SystemTask | None  # 路徑改為複本的項目；失敗時是 None
    destination: Path
    files: int = 0
    size_bytes: int = 0
    seconds: float = 0.0
    error: str | None = None
    failed_files: tuple[str, ...] = ()


# ========== 空間檢查（FR-47） ==========

def required_bytes(items: Sequence[Software | SystemTask]) -> int:
    """要複製的總大小：先複製的軟體子資料夾，加上任務的 .cmd（一律先複製，DD16）"""
    total = 0
    for item in items:
        if isinstance(item, SystemTask):
            total += _size_of_file(item.script)
        elif item.copy_first:
            total += _size_of_folder(item.folder)
    return total


def check_space(target_dir: Path, needed: int) -> str | None:
    """可用空間不夠時回傳原因，夠時回傳 None。比較時加上 1 GB 餘裕"""
    required = needed + MARGIN_BYTES
    free = shutil.disk_usage(target_dir).free
    if free >= required:
        return None
    return (f'空間不足：需要 {_gb(required)}（含 1 GB 餘裕），'
            f'{target_dir} 所在的磁碟只剩 {_gb(free)}')


# ========== 建立 ==========

def create(downloads: Path, *, secure: bool = True) -> Path:
    """在下載資料夾建立這一輪的暫存資料夾，寫入標記檔，再限制為只有系統管理員可以寫入。

    secure=False 只給測試用：一般權限的測試設了權限之後，就無法在裡面寫入。
    設定權限失敗時拋出 OSError：不可以在一般使用者可以寫入的資料夾裡執行（NFR-07）。
    """
    base = f'{PREFIX}{datetime.now():%Y%m%d_%H%M%S}'
    n = 1
    while True:
        path = downloads / (base if n == 1 else f'{base}_{n}')
        try:
            path.mkdir(parents=True)
            break
        except FileExistsError:  # 同一秒內再建立一個
            n += 1
    (path / MARKER).write_text(f'{PRODUCT_NAME} {__version__}\n'
                               f'created={datetime.now():%Y-%m-%d %H:%M:%S}\n'
                               f'pid={os.getpid()}\n', encoding='utf-8')
    if secure:
        _restrict_to_admins(path)
    return path


def _restrict_to_admins(path: Path) -> None:
    """整個權限清單換成只有系統管理員與 SYSTEM，禁止繼承，擁有者改為 Administrators；
    已經在裡面的標記檔也重設為只從資料夾繼承。

    不能只移除繼承的權限（icacls /inheritance:r）：使用者資料夾的權限沒有自動繼承的標記，
    子資料夾得到的使用者完整控制移除不掉（T44 驗收發現，設計第 7.7 節）。
    """
    # 先處理裡面的檔案：資料夾設定之後，不是系統管理員（只有測試）就無法再列出內容。
    # 它們只從資料夾繼承，資料夾的新權限會自動套用到它們
    error = 0
    for child in list(path.iterdir()):
        error = _set_security(child, _INHERIT_ONLY, 0x4 | 0x20000000)  # DACL、UNPROTECTED_DACL
        if error:
            path = child
            break
    if error == 0:
        owner_dacl = 0x1 | 0x4 | 0x80000000  # OWNER、DACL、PROTECTED_DACL
        error = _set_security(path, _ADMIN_ONLY, owner_dacl)
        if error == 1307:  # ERROR_INVALID_OWNER：不是系統管理員（只有測試），保留原本的擁有者
            error = _set_security(path, _ADMIN_ONLY, owner_dacl & ~0x1)
    if error:
        import ctypes
        raise OSError(f'無法設定暫存資料夾的權限：{path}：{ctypes.FormatError(error).strip()}（{error}）')


def _set_security(path: Path, sddl: str, flags: int) -> int:
    """以 SDDL 設定擁有者與 DACL（SetNamedSecurityInfoW），回傳 Windows 的錯誤碼，0 為成功"""
    import ctypes
    from ctypes import wintypes
    advapi32 = ctypes.WinDLL('advapi32', use_last_error=True)
    convert = advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    advapi32.GetSecurityDescriptorOwner.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
                                                    ctypes.POINTER(wintypes.BOOL)]
    advapi32.GetSecurityDescriptorDacl.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL),
                                                   ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.BOOL)]
    advapi32.SetNamedSecurityInfoW.argtypes = [wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD, ctypes.c_void_p,
                                               ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    advapi32.SetNamedSecurityInfoW.restype = wintypes.DWORD
    descriptor = ctypes.c_void_p()
    if not convert(sddl, 1, ctypes.byref(descriptor), None):
        return ctypes.get_last_error()
    try:
        owner, dacl = ctypes.c_void_p(), ctypes.c_void_p()
        present, defaulted = wintypes.BOOL(), wintypes.BOOL()
        advapi32.GetSecurityDescriptorOwner(descriptor, ctypes.byref(owner), ctypes.byref(defaulted))
        advapi32.GetSecurityDescriptorDacl(descriptor, ctypes.byref(present), ctypes.byref(dacl),
                                           ctypes.byref(defaulted))
        return advapi32.SetNamedSecurityInfoW(str(path), 1, flags, owner if flags & 0x1 else None, None, dacl,
                                              None)  # 1 = SE_FILE_OBJECT
    finally:
        ctypes.windll.kernel32.LocalFree(descriptor)


# ========== 複製（FR-46、FR-47） ==========

def copy_software(stage: Path, resource_dir: Path, item: Software) -> CopyResult:
    """把軟體子資料夾複製到暫存資料夾，保留相對於資源資料夾的路徑。

    失敗時刪除複製到一半的檔案，回傳的 item 是 None；其他項目照常（FR-47）。
    """
    try:
        relative = item.folder.relative_to(resource_dir)
    except ValueError:
        relative = Path(item.folder.name)
    destination = stage / relative
    started = time.monotonic()
    copied = {'files': 0, 'bytes': 0}

    def copy_and_count(src, dst, **kwargs):
        result = shutil.copy2(src, dst, **kwargs)
        copied['files'] += 1
        copied['bytes'] += os.path.getsize(dst)
        return result

    def failed(error, failed_files=()):
        _remove_partial(destination)
        return CopyResult(None, destination, copied['files'], copied['bytes'],
                          time.monotonic() - started, error, tuple(failed_files))

    try:
        shutil.copytree(item.folder, destination, copy_function=copy_and_count)
    except shutil.Error as e:
        # copytree 會先複製其他檔案，最後把每個失敗的檔案一起回報
        files = [f'{src}：{why}' for src, _dst, why in e.args[0]]
        return failed(f'{len(files)} 個檔案複製失敗，例如 {files[0]}', files)
    except OSError as e:
        return failed(f'{type(e).__name__}: {e}')

    staged = replace(item, folder=destination, executable=destination / item.executable.name)
    return CopyResult(staged, destination, copied['files'], copied['bytes'], time.monotonic() - started)


def copy_script(stage: Path, task: SystemTask) -> CopyResult:
    """把任務的 .cmd 複製到 <暫存資料夾>\\tasks\\（DD16）"""
    destination = stage / TASKS_DIR / task.script.name
    started = time.monotonic()
    try:
        destination.parent.mkdir(exist_ok=True)
        shutil.copy2(task.script, destination)
    except OSError as e:
        destination.unlink(missing_ok=True)
        return CopyResult(None, destination, error=f'{type(e).__name__}: {e}',
                          seconds=time.monotonic() - started)
    return CopyResult(replace(task, script=destination), destination, 1, destination.stat().st_size,
                      time.monotonic() - started)


def _remove_partial(path: Path) -> None:
    if path.exists():
        _remove(path)


# ========== 刪除（FR-48） ==========

def is_safe_to_delete(path: Path, downloads: Path, resource_dir: Path) -> bool:
    """只刪除同時符合下列條件的資料夾（設計第 7.7 節）：
    1. 直接位於下載資料夾底下
    2. 名稱以 Helper_ 開頭，或以 Hpler_ 開頭（3.0.0、3.0.1 建立的）
    3. 有和名稱同一組的標記檔（STAGE_NAMES）
    4. 不是資源資料夾，也不在資源資料夾裡面，也不包含資源資料夾
    另外，資料夾本身是連結（junction 或 symlink）時不刪：不能讓連結把刪除帶到別的地方。
    """
    if path.is_symlink() or path.is_junction() or not path.is_dir():
        return False
    try:
        target, parent, resources = path.resolve(), downloads.resolve(), resource_dir.resolve()
    except OSError:
        return False
    marker = _marker_for(target.name)
    return (_same(target.parent, parent)
            and marker is not None
            and (target / marker).is_file()
            and not _inside(target, resources)
            and not _inside(resources, target))


def cleanup(downloads: Path, current: Path | None, resource_dir: Path, *,
            retry_seconds: float = 60, retry_interval: float = 2) -> CleanupResult:
    """刪除這一輪的暫存資料夾，以及下載資料夾裡其他帶標記檔的 Helper_*、舊版的 Hpler_*
    （先前異常結束留下的）。

    被佔用的檔案每隔 retry_interval 秒重試，最多 retry_seconds 秒；仍刪不掉的列在
    leftovers，資料夾留到下一輪再刪。不可靜默略過。
    """
    candidates = [current] if current is not None and current.exists() else []
    if downloads.is_dir():
        candidates += [p for p in sorted(downloads.iterdir())
                       if _marker_for(p.name) and not (current and _same(p, current))]
    targets = [p for p in candidates if is_safe_to_delete(p, downloads, resource_dir)]
    leftovers = []
    if current in candidates and current not in targets:
        leftovers.append(f'{current}：不符合刪除的安全條件，沒有刪除')

    deadline = time.monotonic() + retry_seconds
    remaining, errors = targets, {}
    while remaining:
        errors = {path: _delete_stage(path) for path in remaining}
        remaining = [path for path in remaining if path.exists()]
        if not remaining or time.monotonic() >= deadline:
            break
        time.sleep(retry_interval)

    for path in remaining:
        leftovers += [f'{file}：{reason}' for file, reason in errors.get(path, [])] or [f'{path}：刪不掉']
    removed = tuple(path for path in targets if not path.exists())
    return CleanupResult(removed=removed, leftovers=tuple(leftovers))


def _delete_stage(stage: Path) -> list[tuple[str, str]]:
    """刪除暫存資料夾，回傳刪不掉的 (路徑, 原因)。

    標記檔最後才刪：有檔案刪不掉時保留標記檔，下一輪才認得出這是工具建立的資料夾，
    可以再刪一次（否則就永遠刪不掉了）。舊版的資料夾保留的是它自己的標記檔。
    """
    marker = _marker_for(stage.name) or MARKER
    errors = []
    for child in stage.iterdir():
        if child.name != marker:
            errors += _remove(child)
    if not errors:
        errors += _remove(stage / marker)
    if not errors:
        try:
            stage.rmdir()
        except OSError as e:
            errors.append((str(stage), e.strerror or str(e)))
    return errors


def _remove(path: Path) -> list[tuple[str, str]]:
    """刪除一個檔案或資料夾；連結（junction、symlink）只刪除連結本身"""
    if path.is_dir() and not (path.is_symlink() or path.is_junction()):
        return _rmtree(path)
    remove = os.rmdir if path.is_dir() else os.unlink  # 指向資料夾的連結用 rmdir 刪除
    try:
        remove(path)
    except PermissionError:
        try:
            os.chmod(path, stat.S_IWRITE)  # 唯讀檔
            remove(path)
        except OSError as e:
            return [(str(path), e.strerror or str(e))]
    except OSError as e:
        return [(str(path), e.strerror or str(e))]
    return []


def _rmtree(path: Path) -> list[tuple[str, str]]:
    """刪除整個資料夾，回傳刪不掉的 (路徑, 原因)。唯讀檔先改成可寫入再刪。
    目錄連結只刪除連結本身（Python 3.8 起 shutil.rmtree 的行為）"""
    errors = []

    def on_error(func, failed_path, exc):
        if isinstance(exc, PermissionError):
            try:
                os.chmod(failed_path, stat.S_IWRITE)
                func(failed_path)
                return
            except OSError as retry_exc:
                exc = retry_exc
        errors.append((str(failed_path), exc.strerror or str(exc)))

    shutil.rmtree(path, onexc=on_error)
    return errors


# ========== 小工具 ==========

def _marker_for(name: str) -> str | None:
    """名稱對應的標記檔（STAGE_NAMES）；不是工具建立的名稱時回傳 None"""
    return next((marker for prefix, marker in STAGE_NAMES if name.startswith(prefix)), None)


def _size_of_file(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _size_of_folder(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        total += sum(_size_of_file(Path(root) / name) for name in files)
    return total


def _gb(size_bytes: int) -> str:
    return f'{size_bytes / 1024 ** 3:.1f} GB'


def _same(a: Path, b: Path) -> bool:
    return os.path.normcase(str(a)) == os.path.normcase(str(b))


def _inside(child: Path, parent: Path) -> bool:
    """child 就是 parent，或在 parent 裡面（不分大小寫）"""
    c, p = os.path.normcase(str(child)), os.path.normcase(str(parent)).rstrip('\\/')
    return c == p or c.startswith(p + os.sep)
