"""Helper 進入點（設計第 6.1、10 節）

權限 → 找出資源資料夾 → 讀取設定 → 啟動介面。

打包後的 helper.exe 由執行檔的宣告要求提權（DD1）：Windows 在程式啟動之前就跳出 UAC，
這裡不需要處理。直接執行 .py（只用於開發）時，才由這裡以系統管理員身分重新啟動。
"""
import sys
import traceback
from pathlib import Path

from hpler import PRODUCT_NAME, admin, config, gui, paths


def program_name() -> str:
    """錯誤訊息裡的主程式名稱：打包後是執行檔，直接執行時是這個 .py"""
    return Path(sys.executable if getattr(sys, 'frozen', False) else __file__).name


def start(args: list[str]) -> int:
    """設計第 6.1 節的流程，回傳結束代碼"""
    if admin.needs_relaunch():
        error = admin.relaunch_as_admin(Path(__file__), args)
        if error is not None:
            gui.show_error(f'{PRODUCT_NAME} 無法啟動', error)
            return 1
        return 0  # 以系統管理員身分啟動的新行程接手

    load = config.load(paths.find_resource_dir())
    if any(p.severity == 'fatal' for p in load.problems):
        gui.show_fatal(list(load.problems), paths.get_current_dir(), program_name())  # FR-14
        return 1
    gui.run(load, is_admin=admin.is_admin())  # 其他問題由介面顯示問題清單（FR-36）
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return start(sys.argv[1:] if argv is None else argv)
    except Exception:  # 邊界的最外層（設計第 13 節）：打包後沒有主控台，錯誤內容要顯示出來
        gui.show_error(f'{PRODUCT_NAME} 發生非預期的錯誤', traceback.format_exc())
        return 1


if __name__ == '__main__':
    sys.exit(main())
