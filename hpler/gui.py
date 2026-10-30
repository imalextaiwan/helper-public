"""Helper 3.0 介面（設計第 6.3、9 節；FR-30～FR-36、FR-46～FR-48、FR-51～FR-53）

沿用 2.0 的版面：標題列、兩個分頁、按鈕列、狀態列、免責聲明。和 2.0 不同的地方：
- 系統設定的分類依 XML 的 <category> 動態產生（FR-32）
- 勾選狀態以 id 對應，同名的項目不會互相覆蓋
- 執行中的進度條是「不確定」模式的動畫，完成時填滿（DD9）
- 啟動時有問題就顯示問題清單（FR-36）
- 字型、顏色、文字集中在檔案開頭；產品名稱與版本號取自 hpler/__init__.py

只有這個模組可以 import tkinter（設計第 2.2 節）。執行在背景執行緒，由 runner 負責；
這裡只透過 root.after 在主執行緒更新畫面，所以執行期間介面不會凍結（FR-40）。
"""
from __future__ import annotations

import os
import sys
import threading
import tkinter as tk
import traceback
from collections import Counter
from pathlib import Path
from tkinter import font as tkfont
from tkinter import messagebox, ttk
from typing import Callable

from PIL import Image, ImageTk

from . import PRODUCT_NAME, __version__, logs, runner
from .models import BatchResult, LoadResult, Problem, Software, SystemTask, TaskResult

# ========== 常數 ==========

FONT = '微軟正黑體'
COLOR_TITLE_BG = '#2196F3'
COLOR_TITLE_SUB = '#BBDEFB'
COLOR_BG = '#F5F5F5'
COLOR_TASK_BG = '#F8F9FA'
COLOR_TEXT_DIM = '#666666'
COLOR_STATUS = '#2196F3'
COLOR_DISCLAIMER = '#cc0000'
BUTTONS = {  # 文字、寬度、底色、字級
    'select_all': ('全選', 10, '#4CAF50', 8),
    'select_none': ('全不選', 10, '#f44336', 8),
    'start': ('開始執行', 14, '#2196F3', 9),
    'pause': ('暫停', 8, '#FF5722', 8),
    'cancel': ('取消', 8, '#9E9E9E', 8),
    'log_folder': ('日誌資料夾', 12, '#607D8B', 8),
}
MIN_WIDTH, MIN_HEIGHT = 850, 600  # FR-35
ICON_SIZE = 24
# 資源資料夾裡的視窗圖示，依序使用第一個存在的。3.0.1 以前的部署是 hpler_icon.ico，
# 只換執行檔也要有圖示（設計第 2.4 節、FR-23）
WINDOW_ICONS = ('helper_icon.ico', 'hpler_icon.ico')

WINDOW_TITLE = f'{PRODUCT_NAME} {__version__} - 軟體安裝與系統設定'
HEADING = f'{PRODUCT_NAME} {__version__} - 軟體安裝自動化與系統設定工具'
SUBHEADING = f'版本 {__version__} | Automation Team'
TAB_NAMES = {'software': '軟體安裝', 'tasks': '系統設定'}
DISCLAIMER = ('本工具僅提供第三方軟體安裝與系統設定自動化功能，所有軟體與任務之智慧財產權均歸原權利人所有。'
              '本工具不對內容、品質、功能或安全性負責，使用者應自行承擔風險並備份重要資料。'
              f'本工具之目的在於簡化部署與設定流程。 {PRODUCT_NAME} {__version__}')
STATE_TEXT = {'waiting': '等待中', 'copying': '複製中', 'copied': '已複製', 'running': '執行中'}
SEVERITY_TEXT = {'fatal': '嚴重', 'error': '錯誤', 'warning': '提醒'}
MAX_LEFTOVERS_SHOWN = 10

RunBatch = Callable[..., BatchResult]


# ========== 啟動時的錯誤與問題清單（設計第 6.1、6.3 節） ==========

def fatal_message(problems: list[Problem], exe_dir: Path, exe_name: str) -> str:
    """software.xml 有整個檔案的問題時顯示的訊息：原因與預期的目錄結構（FR-14）"""
    reasons = '\n'.join(p.message for p in problems if p.severity == 'fatal')
    return (f'{reasons}\n\n'
            f'預期的目錄結構：\n'
            f'{exe_dir}\\{exe_name}\n'
            f'{exe_dir}\\helper_software\\software.xml\n'
            f'{exe_dir}\\helper_software\\system_tasks.xml（選用）\n'
            f'{exe_dir}\\helper_software\\tasks\\<任務 id>.cmd\n'
            f'{exe_dir}\\helper_software\\<各軟體子資料夾>\\\n\n'
            f'（資料夾名稱也可以是 Helper）')


def show_fatal(problems: list[Problem], exe_dir: Path, exe_name: str) -> None:
    """不需要主視窗就能顯示的錯誤對話框；呼叫後結束程式"""
    root = tk.Tk()
    root.withdraw()
    try:
        messagebox.showerror(f'{PRODUCT_NAME} 無法啟動', fatal_message(problems, exe_dir, exe_name), parent=root)
    finally:
        root.destroy()


def show_error(title: str, message: str) -> None:
    """沒有主視窗時的錯誤對話框（例如提權失敗）"""
    root = tk.Tk()
    root.withdraw()
    try:
        messagebox.showerror(title, message, parent=root)
    finally:
        root.destroy()


def problems_text(problems: list[Problem]) -> str:
    """依檔案分組列出問題；每一筆顯示嚴重度、項目 id 與原因"""
    lines = []
    for file in dict.fromkeys(p.file for p in problems):
        lines.append(f'【{file}】')
        for p in (p for p in problems if p.file == file):
            lines.append(f'  [{SEVERITY_TEXT[p.severity]}] {p.item_id or "-"}：{p.message}')
        lines.append('')
    return '\n'.join(lines).rstrip() + '\n'


class ProblemWindow:
    """可以捲動的問題清單，附「複製」按鈕；關掉後工具照常使用（設計第 6.3 節）"""

    def __init__(self, root: tk.Misc, problems: list[Problem]):
        self.text = problems_text(problems)
        self.window = tk.Toplevel(root)
        self.window.title(f'{PRODUCT_NAME} - 設定檔的問題（{len(problems)} 筆）')
        self.window.geometry('760x420')
        self.window.transient(root)
        tk.Label(self.window, text='以下項目有問題，已略過或改用預設值；其他項目照常使用。',
                 font=(FONT, 9, 'bold'), anchor='w').pack(fill=tk.X, padx=10, pady=(10, 4))
        # 按鈕先排在底部：文字區塊再大，按鈕也一定看得到
        buttons = tk.Frame(self.window)
        buttons.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=10)
        tk.Button(buttons, text='關閉', width=10, command=self.window.destroy).pack(side=tk.RIGHT, padx=3)
        tk.Button(buttons, text='複製', width=10, command=self.copy).pack(side=tk.RIGHT, padx=3)
        frame = tk.Frame(self.window)
        frame.pack(fill=tk.BOTH, expand=True, padx=10)
        scrollbar = ttk.Scrollbar(frame, orient='vertical')
        self.box = tk.Text(frame, font=(FONT, 9), wrap='word', height=10, yscrollcommand=scrollbar.set)
        scrollbar.configure(command=self.box.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.box.insert('1.0', self.text)
        self.box.configure(state='disabled')

    def copy(self) -> None:
        """方便回報給維護者"""
        self.window.clipboard_clear()
        self.window.clipboard_append(self.text)


# ========== 主視窗 ==========

def window_icon(resource_dir: Path) -> Path | None:
    """資源資料夾裡的視窗圖示（WINDOW_ICONS 的第一個存在的）；都沒有時回傳 None，不顯示圖示"""
    return next((resource_dir / name for name in WINDOW_ICONS if (resource_dir / name).is_file()), None)


class Row:
    """清單上一個項目的勾選框與進度"""

    def __init__(self, var: tk.BooleanVar, frame: tk.Frame, bar: ttk.Progressbar, label: tk.Label, name: tk.Widget):
        self.var, self.frame, self.bar, self.label, self.name = var, frame, bar, label, name

    def show(self, text: str, *, busy: bool = False, done: bool = False) -> None:
        if not self.frame.winfo_ismapped():
            # 排在名稱前面：先分到空間，名稱再長也不會把狀態擠到看不見的地方（T44）
            self.frame.pack(side=tk.RIGHT, fill=tk.X, padx=(8, 0), before=self.name)
        self.bar.stop()
        if busy:
            self.bar.configure(mode='indeterminate')  # 安裝程式不會回報進度（DD9）
            self.bar.start(15)
        else:
            self.bar.configure(mode='determinate', value=100 if done else 0)
        self.label.configure(text=text)

    def hide(self) -> None:
        self.bar.stop()
        self.bar.configure(mode='determinate', value=0)
        self.label.configure(text='')
        self.frame.pack_forget()


class App:
    """主視窗。run_batch 可以替換，測試用"""

    def __init__(self, root: tk.Tk, load: LoadResult, *, is_admin: bool = True,
                 run_batch: RunBatch = runner.run_batch):
        self.root, self.load, self.is_admin, self._run_batch = root, load, is_admin, run_batch
        self.rows: dict[str, dict[str, Row]] = {'software': {}, 'tasks': {}}
        self.items: dict[str, list[Software | SystemTask]] = {
            'software': list(load.software),
            'tasks': [task for category in load.categories for task in category.tasks],
        }
        self.cancel = threading.Event()
        self.resume = threading.Event()
        self.resume.set()
        self.running = False
        self._icons: list[ImageTk.PhotoImage] = []  # 保留參照，圖示才不會被回收

        # 不能用 self 的方法：root 和 App 互相參照時，會由其他執行緒的垃圾回收釋放 Tk，造成當機
        root.report_callback_exception = show_callback_error
        self._setup_window()
        self._build()
        if load.problems:
            self.problem_window = ProblemWindow(root, list(load.problems))  # FR-36

    # ---------- 版面 ----------

    def _setup_window(self) -> None:
        self.root.title(WINDOW_TITLE)
        width = min(1000, int(self.root.winfo_screenwidth() * 0.85))
        height = min(int(self.root.winfo_screenheight() * 0.7), self.root.winfo_screenheight() - 100)
        self.root.geometry(f'{width}x{height}')
        self.root.minsize(MIN_WIDTH, MIN_HEIGHT)
        icon = window_icon(self.load.resource_dir)
        if icon is not None and sys.platform == 'win32':
            self.root.iconbitmap(str(icon))
        tkfont.nametofont('TkDefaultFont').configure(size=8)
        style = ttk.Style()
        style.configure('Hpler.TNotebook.Tab', font=(FONT, 11, 'bold'), padding=(20, 8))
        self.root.protocol('WM_DELETE_WINDOW', self.close)

    def _build(self) -> None:
        # 標題、分頁（可伸縮）、按鈕、狀態、免責聲明：下方按鈕一律看得到（FR-35）
        for row, weight in enumerate((0, 1, 0, 0, 0)):
            self.root.grid_rowconfigure(row, weight=weight)
        self.root.grid_columnconfigure(0, weight=1)

        title = tk.Frame(self.root, bg=COLOR_TITLE_BG, height=60)
        title.grid(row=0, column=0, sticky='ew')
        title.grid_propagate(False)
        tk.Label(title, text=HEADING, font=(FONT, 14, 'bold'), bg=COLOR_TITLE_BG, fg='white').pack(expand=True)
        tk.Label(title, text=SUBHEADING, font=(FONT, 8), bg=COLOR_TITLE_BG, fg=COLOR_TITLE_SUB).pack()

        center = tk.Frame(self.root, bg=COLOR_BG)
        center.grid(row=1, column=0, sticky='nsew', padx=15, pady=10)
        self.notebook = ttk.Notebook(center, style='Hpler.TNotebook')
        self.notebook.pack(fill=tk.BOTH, expand=True)
        self.tabs = {'software': ttk.Frame(self.notebook), 'tasks': ttk.Frame(self.notebook)}
        for mode, frame in self.tabs.items():
            self.notebook.add(frame, text=TAB_NAMES[mode])
        self._build_software_tab()
        self._build_tasks_tab()

        self._build_buttons()
        self.status = tk.Label(self.root, text=f'{PRODUCT_NAME} 準備就緒', font=(FONT, 9, 'bold'),
                               fg=COLOR_STATUS, pady=3)
        self.status.grid(row=3, column=0, sticky='ew', padx=10, pady=3)
        disclaimer = tk.LabelFrame(self.root, text='免責聲明與著作權', font=(FONT, 8, 'bold'),
                                   fg=COLOR_DISCLAIMER, padx=8, pady=3)
        disclaimer.grid(row=4, column=0, sticky='ew', padx=10, pady=3)
        tk.Label(disclaimer, text=DISCLAIMER, font=(FONT, 8), fg=COLOR_TEXT_DIM, wraplength=900,
                 justify='left', anchor='w', bg='white', padx=5, pady=3).pack(pady=2, padx=2, fill=tk.BOTH)

    def _scrollable(self, parent: tk.Misc, bg: str) -> tk.Frame:
        """可以捲動的區塊；滑鼠在上面時，滾輪捲動這一個區塊"""
        canvas = tk.Canvas(parent, bg=bg, highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient='vertical', command=canvas.yview)
        inner = tk.Frame(canvas, bg=bg)
        inner.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        window = canvas.create_window((0, 0), window=inner, anchor='nw')
        # 內容和看得見的範圍一樣寬：太長的名稱換行，不會超出右邊（T44）
        canvas.bind('<Configure>', lambda e: canvas.itemconfigure(window, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

        def wheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), 'units')

        canvas.bind('<Enter>', lambda e: canvas.bind_all('<MouseWheel>', wheel))
        canvas.bind('<Leave>', lambda e: canvas.unbind_all('<MouseWheel>'))
        return inner

    @staticmethod
    def _columns(parent: tk.Misc, bg: str, items: list) -> list[tuple[tk.Frame, object]]:
        """左右兩欄，前一半放左欄（FR-31）"""
        container = tk.Frame(parent, bg=bg)
        container.pack(fill=tk.BOTH, expand=True, padx=12, pady=8)
        for column in (0, 1):  # 兩欄一樣寬，不隨名稱的長短變動
            container.grid_columnconfigure(column, weight=1, uniform='columns')
        left = tk.Frame(container, bg=bg)
        left.grid(row=0, column=0, sticky='nsew', padx=(0, 10))
        right = tk.Frame(container, bg=bg)
        right.grid(row=0, column=1, sticky='nsew', padx=(10, 0))
        middle = len(items) // 2
        return [(left, item) for item in items[:middle]] + [(right, item) for item in items[middle:]]

    def _empty(self, parent: tk.Misc, text: str, bg: str) -> None:
        tk.Label(parent, text=text, font=(FONT, 9), bg=bg, fg=COLOR_TEXT_DIM, justify='left').pack(pady=40)

    def _build_software_tab(self) -> None:
        box = tk.LabelFrame(self.tabs['software'], text='選擇測試軟體套件', font=(FONT, 10, 'bold'))
        box.pack(padx=8, pady=10, fill=tk.BOTH, expand=True)
        inner = self._scrollable(box, COLOR_BG)
        if not self.load.software:
            self._empty(inner, '沒有可以安裝的軟體：請檢查 software.xml 與問題清單', COLOR_BG)
        for column, item in self._columns(inner, COLOR_BG, self.items['software']):
            self._software_row(column, item)

    def _software_row(self, parent: tk.Frame, item: Software) -> None:
        frame = tk.Frame(parent, bg=COLOR_BG)
        frame.pack(fill=tk.X, padx=5, pady=2)
        var = tk.BooleanVar(value=True)  # 預設全部勾選（FR-31）
        icon = self._load_icon(item.icon)
        check = tk.Checkbutton(frame, text=f' {item.name}', variable=var, font=(FONT, 9), image=icon or '',
                               compound='left', anchor='w', justify='left', bg=COLOR_BG, selectcolor='#E3F2FD',
                               activebackground='#E8F5E8', padx=5, pady=1)
        check.pack(side=tk.LEFT, fill=tk.X)
        row = self.rows['software'][item.id] = self._progress(frame, var, COLOR_BG, 80, 12, check)
        # 勾選框、圖示與狀態以外的寬度給名稱，太長就換行
        others = 40 + (ICON_SIZE + 8 if icon else 0)
        self._wrap(frame, row, [(check, others)])

    def _build_tasks_tab(self) -> None:
        tab = self.tabs['tasks']
        if not self.load.categories:
            reasons = [p.message for p in self.load.problems if p.file == 'system_tasks.xml' and not p.item_id]
            self._empty(tab, '系統設定無法使用：\n' + ('\n'.join(reasons) or '沒有可用的系統設定任務'), COLOR_BG)
            return
        for category in self.load.categories:  # 依 XML 的 <category> 產生區塊（FR-32）
            box = tk.LabelFrame(tab, text=category.name, font=(FONT, 10, 'bold'))
            box.pack(padx=15, pady=(8, 5), fill=tk.BOTH, expand=True)
            inner = self._scrollable(box, COLOR_TASK_BG)
            for column, task in self._columns(inner, COLOR_TASK_BG, list(category.tasks)):
                self._task_row(column, task)

    def _task_row(self, parent: tk.Frame, task: SystemTask) -> None:
        frame = tk.Frame(parent, bg=COLOR_TASK_BG, relief='ridge', bd=1)
        frame.pack(fill=tk.X, padx=3, pady=3)
        text = tk.Frame(frame, bg=COLOR_TASK_BG)
        text.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8, pady=4)
        var = tk.BooleanVar(value=True)
        check = tk.Checkbutton(text, text=f' {task.name}', variable=var, font=(FONT, 9, 'bold'), anchor='w',
                               justify='left', bg=COLOR_TASK_BG, selectcolor='#E3F2FD', activebackground='#E8F5E8')
        check.pack(anchor='w')
        wrapped = [(check, 56)]
        if task.description:
            description = tk.Label(text, text=task.description, font=(FONT, 8), fg=COLOR_TEXT_DIM, bg=COLOR_TASK_BG,
                                   anchor='w', justify='left')
            description.pack(anchor='w', padx=(24, 0))
            wrapped.append((description, 56))
        row = self.rows['tasks'][task.id] = self._progress(frame, var, COLOR_TASK_BG, 70, 12, text)
        self._wrap(frame, row, wrapped)

    @staticmethod
    def _wrap(frame: tk.Frame, row: Row, widgets: list[tuple[tk.Widget, int]]) -> None:
        """依這一列的寬度設定換行寬度。狀態的位置一開始就保留，執行時版面不會跳動。

        寬度只差幾個像素時不重設：兩欄平分寬度時，奇數的那一個像素會隨內容在兩欄之間移動，
        重設換行寬度又會改變內容，結果無限循環、介面卡住（T44 修正時以真實資料發現）。
        """
        last = [0]

        def fit(event):
            if abs(event.width - last[0]) <= 4:
                return
            last[0] = event.width
            for widget, others in widgets:
                widget.configure(wraplength=max(120, event.width - row.frame.winfo_reqwidth() - others))
        frame.bind('<Configure>', fit)

    @staticmethod
    def _progress(frame: tk.Frame, var: tk.BooleanVar, bg: str, length: int, width: int, name: tk.Widget) -> Row:
        holder = tk.Frame(frame, bg=bg)  # 執行時才顯示
        bar = ttk.Progressbar(holder, orient=tk.HORIZONTAL, length=length, mode='determinate')
        bar.pack(side=tk.LEFT)
        label = tk.Label(holder, text='', font=(FONT, 7), bg=bg, fg=COLOR_TEXT_DIM, width=width)
        label.pack(side=tk.LEFT, padx=(3, 0))
        return Row(var, holder, bar, label, name)

    def _load_icon(self, path: Path | None) -> ImageTk.PhotoImage | None:
        """子資料夾裡的圖示（FR-16）；讀不到就不顯示圖示，項目照常顯示"""
        if path is None:
            return None
        try:
            with Image.open(path) as image:
                photo = ImageTk.PhotoImage(image.convert('RGBA').resize((ICON_SIZE, ICON_SIZE), Image.LANCZOS))
        except (OSError, ValueError):
            return None
        self._icons.append(photo)
        return photo

    def _build_buttons(self) -> None:
        bar = tk.Frame(self.root, bg=COLOR_BG, relief='raised', bd=1)
        bar.grid(row=2, column=0, sticky='ew', pady=5)
        left = tk.Frame(bar, bg=COLOR_BG)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=5)
        controls = tk.Frame(bar, bg=COLOR_BG)
        controls.pack(side=tk.LEFT, padx=(10, 0), fill=tk.Y)
        right = tk.Frame(bar, bg=COLOR_BG)
        right.pack(side=tk.RIGHT, padx=5)

        def button(parent, key, command, **pack):
            text, width, color, size = BUTTONS[key]
            widget = tk.Button(parent, text=text, command=command, width=width, height=1,
                               font=(FONT, size, 'bold'), bg=color, fg='white', relief='raised', cursor='hand2')
            widget.pack(side=pack.pop('side', tk.LEFT), **pack)
            return widget

        self.buttons = {
            'select_all': button(left, 'select_all', self.select_all, padx=3),
            'select_none': button(left, 'select_none', self.select_none, padx=3),
            'start': button(left, 'start', self.start, padx=10),
            'pause': button(controls, 'pause', self.toggle_pause, padx=3),
            'cancel': button(controls, 'cancel', self.cancel_run, padx=3),
            'log_folder': button(right, 'log_folder', self.open_log_folder, side=tk.RIGHT, padx=3),
        }
        self._set_running(False)

    # ---------- 操作 ----------

    def current_mode(self) -> str:
        return 'software' if self.notebook.select() == str(self.tabs['software']) else 'tasks'

    def select_all(self) -> None:
        """只作用於目前的分頁（FR-33）"""
        for row in self.rows[self.current_mode()].values():
            row.var.set(True)

    def select_none(self) -> None:
        for row in self.rows[self.current_mode()].values():
            row.var.set(False)

    def selected(self, mode: str) -> list[Software | SystemTask]:
        """勾選的項目，依清單（XML）的順序"""
        return [item for item in self.items[mode] if self.rows[mode][item.id].var.get()]

    def start(self) -> None:
        mode = self.current_mode()
        items = self.selected(mode)
        if not items:
            messagebox.showwarning('提示', f'請至少勾選一個{"軟體" if mode == "software" else "系統設定任務"}',
                                   parent=self.root)
            return
        for row in self.rows[mode].values():
            row.hide()
        self.cancel.clear()
        self.resume.set()
        self._set_running(True)
        self._set_status(f'開始{TAB_NAMES[mode]}，請稍候…')
        timeout = self.load.software_timeout if mode == 'software' else self.load.task_timeout
        threading.Thread(target=self._worker, args=(mode, items, timeout), daemon=True).start()

    def _worker(self, mode: str, items: list, timeout: int) -> None:
        """背景執行緒：執行一輪，完成後回到主執行緒處理結果"""
        def on_progress(item_id: str, state: str, result: TaskResult | None) -> None:
            self.root.after(0, self._update_row, mode, item_id, state, result)

        try:
            result = self._run_batch(mode, items, resource_dir=self.load.resource_dir, timeout=timeout,
                                     problems=self.load.problems, is_admin=self.is_admin,
                                     cancel=self.cancel, resume=self.resume, on_progress=on_progress)
        except Exception as e:  # 邊界：非預期錯誤也一定恢復按鈕並顯示原因（FR-53、設計第 13 節）
            message = (f'執行過程發生非預期的錯誤，已停止。\n\n{type(e).__name__}: {e}\n\n'
                       f'詳細內容見日誌：{logs.log_dir()}')
            self.root.after(0, self._finish_failed, message)
            return
        self.root.after(0, self._finish, mode, items, result)

    def _update_row(self, mode: str, item_id: str, state: str, result: TaskResult | None) -> None:
        row = self.rows[mode].get(item_id)
        if row is None:
            return
        if state == 'done' or state == 'copy_failed':
            row.show(result_text(result), done=True)
        else:
            row.show(STATE_TEXT[state], busy=state in ('copying', 'running'))
        if state in ('copying', 'running'):
            verb = '複製' if state == 'copying' else '執行'
            name = next((i.name for i in self.items[mode] if i.id == item_id), item_id)
            self._set_status(f'{verb}中：{name}')

    def _finish(self, mode: str, items: list, result: BatchResult) -> None:
        self._set_running(False)
        if result.aborted:
            for row in self.rows[mode].values():
                row.hide()
            self._set_status(f'沒有執行：{result.aborted}')
            messagebox.showerror('無法執行', result.aborted, parent=self.root)
            return
        summary, ok = completion_message(TAB_NAMES[mode], len(items), result, self.cancel.is_set())
        counts = Counter(r.status for r in result.results)
        self._set_status(f'{TAB_NAMES[mode]}完成：成功 {counts["success"]}、'
                         f'失敗 {len(result.results) - counts["success"]}')
        (messagebox.showinfo if ok else messagebox.showwarning)(f'{TAB_NAMES[mode]}完成', summary,
                                                                 parent=self.root)

    def _finish_failed(self, message: str) -> None:
        self._set_running(False)
        self._set_status('執行中斷：發生錯誤')
        messagebox.showerror('執行失敗', message, parent=self.root)

    def toggle_pause(self) -> None:
        """在目前項目完成後暫停；再按一次繼續（FR-43）"""
        if self.resume.is_set():
            self.resume.clear()
            self.buttons['pause'].configure(text='繼續')
            self._set_status('暫停中：目前的項目完成後暫停')
        else:
            self.resume.set()
            self.buttons['pause'].configure(text=BUTTONS['pause'][0])
            self._set_status('繼續執行')

    def cancel_run(self) -> None:
        """在目前項目完成後停止，不再執行剩下的項目（FR-44）"""
        self.cancel.set()
        self.resume.set()  # 暫停中也要能結束等待
        self.buttons['cancel'].configure(state='disabled')
        self.buttons['pause'].configure(state='disabled')
        self._set_status('取消中：目前的項目完成後停止')

    def open_log_folder(self) -> None:
        """開啟日誌所在的資料夾（FR-52）"""
        folder = logs.log_dir()
        try:
            folder.mkdir(parents=True, exist_ok=True)
            os.startfile(folder)
        except OSError as e:
            messagebox.showerror('無法開啟日誌資料夾', f'{folder}\n\n{type(e).__name__}: {e}', parent=self.root)

    def close(self) -> None:
        if self.running and not messagebox.askyesno(
                '確定要關閉嗎？', '正在執行中。現在關閉的話，暫存資料夾會留在「下載」裡，下次執行時才會刪除。\n\n確定要關閉嗎？',
                parent=self.root):
            return
        self.root.destroy()

    def _set_running(self, running: bool) -> None:
        self.running = running
        idle, busy = ('disabled', 'normal') if running else ('normal', 'disabled')
        for key in ('select_all', 'select_none', 'start'):
            self.buttons[key].configure(state=idle)
        self.buttons['pause'].configure(state=busy, text=BUTTONS['pause'][0])
        self.buttons['cancel'].configure(state=busy)

    def _set_status(self, text: str) -> None:
        self.status.configure(text=text)


def show_callback_error(exc_type, exc, tb) -> None:
    """邊界：按鈕等事件裡沒有處理的例外（設計第 13 節）。Tk 預設只印到 stderr，
    打包後沒有主控台就看不到，所以顯示完整的錯誤內容"""
    detail = ''.join(traceback.format_exception(exc_type, exc, tb))
    messagebox.showerror(f'{PRODUCT_NAME} 發生非預期的錯誤', detail)


def result_text(result: TaskResult) -> str:
    """項目旁的狀態文字。成功代碼不是 0 時顯示代碼，提醒可能需要重新開機（設計第 7.2 節）"""
    if result.status == 'success':
        return '成功' if not result.exit_code else f'成功（{result.exit_code}）'
    if result.status == 'failed':
        return f'失敗（{result.exit_code}）'
    return logs.STATUS_NAMES[result.status]


def completion_message(mode_name: str, selected: int, result: BatchResult, cancelled: bool) -> tuple[str, bool]:
    """完成對話框的內容，直接統計 TaskResult.status（FR-51）。回傳 (內容, 是否全部順利)"""
    counts = Counter(r.status for r in result.results)
    failed = len(result.results) - counts['success']
    lines = [f'{PRODUCT_NAME} - {mode_name}{"已取消" if cancelled else "完成"}！', '',
             f'成功：{counts["success"]} 個', f'失敗：{failed} 個']
    details = [f'{logs.STATUS_NAMES[s]} {counts[s]}' for s in ('failed', 'timeout', 'error', 'copy_failed') if counts[s]]
    if details:
        lines.append(f'（{"、".join(details)}）')
    not_run = selected - len(result.results)
    if not_run:
        lines.append(f'沒有執行：{not_run} 個（已取消）')
    if result.cleanup.leftovers:
        lines += ['', '暫存資料夾有檔案刪不掉，下次執行時會再刪除：']
        lines += [f'  {item}' for item in result.cleanup.leftovers[:MAX_LEFTOVERS_SHOWN]]
        if len(result.cleanup.leftovers) > MAX_LEFTOVERS_SHOWN:
            lines.append(f'  …共 {len(result.cleanup.leftovers)} 個，詳見日誌')
    lines += ['', f'詳細日誌：{logs.log_dir()}']
    ok = failed == 0 and not not_run and not result.cleanup.leftovers
    return '\n'.join(lines), ok


# ========== 進入點用 ==========

def run(load: LoadResult, *, is_admin: bool) -> None:
    """建立主視窗，執行到關閉為止（設計第 6.1 節的第 4、5 步）。
    helper.py 不能 import tkinter，所以主迴圈在這裡"""
    root = tk.Tk()
    App(root, load, is_admin=is_admin)
    root.mainloop()
