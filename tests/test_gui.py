"""Helper 3.0 介面（設計第 6.3、9 節；FR-30～FR-36、FR-46～FR-48、FR-51～FR-53）

用真的（隱藏的）Tk 視窗，搭配假的 run_batch：不執行任何程式，只驗證介面的行為。
"""
import dataclasses
import time
from pathlib import Path

import pytest

tk = pytest.importorskip('tkinter')
pytest.importorskip('PIL.ImageTk')

import hpler  # noqa: E402
from hpler import gui, logs  # noqa: E402
from hpler.models import (BatchResult, CleanupResult, LoadResult, Problem, Software, SystemTask,  # noqa: E402
                          TaskCategory, TaskResult)


@pytest.fixture
def boxes(monkeypatch):
    """攔截所有對話框，記錄 (種類, 標題, 內容)"""
    calls = []
    for kind in ('showerror', 'showwarning', 'showinfo'):
        monkeypatch.setattr(gui.messagebox, kind,
                            lambda title, message, _k=kind, **kw: calls.append((_k, title, message)))
    monkeypatch.setattr(gui.messagebox, 'askyesno',
                        lambda title, message, **kw: calls.append(('askyesno', title, message)) or False)
    return calls


def make_load(tmp_path, *, software=('a', 'b', 'c'), categories=None, problems=(), icon_for=None):
    res = tmp_path / 'helper_software'
    items = []
    for name in software:
        folder = res / name
        folder.mkdir(parents=True, exist_ok=True)
        icon = None
        if name == icon_for:
            from PIL import Image
            icon = folder / 'icon.png'
            Image.new('RGB', (64, 64), 'red').save(icon)
        items.append(Software(id=name, name=f'軟體 {name}', folder=folder, executable=folder / 'setup.exe',
                              icon=icon))
    if categories is None:
        categories = [('power', '電源與穩定性優化', ['p1', 'p2']), ('security', '安全性與存取優化', ['s1'])]
    cats = tuple(TaskCategory(id=cid, name=cname, tasks=tuple(
        SystemTask(id=t, name=f'任務 {t}', description=f'{t} 的說明', script=res / 'tasks' / f'{t}.cmd')
        for t in tasks)) for cid, cname, tasks in categories)
    return LoadResult(resource_dir=res, software=tuple(items), software_timeout=1000, categories=cats,
                      task_timeout=300, problems=tuple(problems))


class FakeRun:
    """假的 run_batch：依序回報進度，回傳指定的結果"""

    def __init__(self, statuses=None, *, aborted=None, leftovers=(), raises=None, stop_after=None):
        self.statuses = statuses or {}
        self.aborted, self.leftovers, self.raises, self.stop_after = aborted, leftovers, raises, stop_after
        self.calls = []

    def __call__(self, mode, items, *, resource_dir, timeout, problems, is_admin, cancel, resume, on_progress):
        self.calls.append({'mode': mode, 'ids': [i.id for i in items], 'timeout': timeout,
                           'problems': problems, 'resource_dir': resource_dir})
        if self.raises:
            raise self.raises
        if self.aborted:
            return BatchResult((), CleanupResult((), ()), self.aborted)
        results = []
        for item in items:
            on_progress(item.id, 'waiting', None)
        for item in items[:self.stop_after]:
            on_progress(item.id, 'running', None)
            status, code = self.statuses.get(item.id, ('success', 0))
            result = TaskResult(item.id, status, code, 0.1, '')
            results.append(result)
            on_progress(item.id, 'done', result)
        return BatchResult(tuple(results), CleanupResult((), tuple(self.leftovers)))


def wait_until_idle(root, app, seconds=10):
    """執行主迴圈直到這一輪結束（背景執行緒以 root.after 通知主執行緒，和實際執行相同）"""
    deadline = time.time() + seconds

    def poll():
        if (not app.running) or time.time() > deadline:
            root.after(50, root.quit)  # 讓 _finish 之後排定的畫面更新也處理完
        else:
            root.after(20, poll)

    root.after(20, poll)
    root.mainloop()
    # poll 參照自己，是一個循環：不打斷的話，app 和它的 Tk 變數要等垃圾回收才釋放，
    # 可能在之後的測試的背景執行緒裡發生，而 Tk 只接受主執行緒的呼叫
    poll = None
    assert not app.running, '執行沒有結束'


def build(root, load, run=None):
    app = gui.App(root, load, run_batch=run or FakeRun())
    root.update()
    return app


def switch(app, mode):
    app.notebook.select(app.tabs[mode])
    app.root.update()


# ========== 版面 ==========

def test_title_uses_product_name_and_version(root, tmp_path):
    build(root, make_load(tmp_path))
    assert root.title() == f'{hpler.PRODUCT_NAME} {hpler.__version__} - 軟體安裝與系統設定'


def test_minimum_size(root, tmp_path):
    build(root, make_load(tmp_path))
    assert root.minsize() == (850, 600)  # FR-35


def test_software_listed_in_xml_order_and_checked(root, tmp_path):
    app = build(root, make_load(tmp_path))
    assert list(app.rows['software']) == ['a', 'b', 'c']
    assert all(row.var.get() for row in app.rows['software'].values())  # 預設全部勾選（FR-31）


def test_categories_come_from_xml(root, tmp_path):
    """FR-32：分類依 XML 產生；新增一個分類，介面就多一個區塊"""
    load = make_load(tmp_path, categories=[('a', '第一類', ['t1']), ('b', '第二類', ['t2']), ('c', '網路', ['t3'])])
    app = build(root, load)
    frames = [w for w in app.tabs['tasks'].winfo_children() if isinstance(w, tk.LabelFrame)]
    assert [f.cget('text') for f in frames] == ['第一類', '第二類', '網路']
    assert list(app.rows['tasks']) == ['t1', 't2', 't3']


def test_icon_is_shown(root, tmp_path):
    app = build(root, make_load(tmp_path, icon_for='b'))
    assert len(app._icons) == 1  # FR-16


@pytest.mark.parametrize('files, expected', [
    (['helper_icon.ico', 'hpler_icon.ico'], 'helper_icon.ico'),
    (['hpler_icon.ico'], 'hpler_icon.ico'),  # 3.0.1 以前的部署：只換執行檔也有圖示（FR-23）
    ([], None),
], ids=['new-name-first', 'old-deployment', 'none'])
def test_window_icon(tmp_path, files, expected):
    """視窗圖示：helper_icon.ico 優先，沒有時使用 hpler_icon.ico（設計第 2.4 節）"""
    for name in files:
        (tmp_path / name).write_bytes(b'')
    assert gui.window_icon(tmp_path) == (tmp_path / expected if expected else None)


def test_tasks_tab_when_system_tasks_xml_is_missing(root, tmp_path, boxes):
    """第 6.2 節：系統設定分頁顯示原因，不能執行"""
    problem = Problem('warning', 'system_tasks.xml', None, '找不到 system_tasks.xml：X')
    app = build(root, make_load(tmp_path, categories=[], problems=[problem]))
    labels = [w.cget('text') for w in app.tabs['tasks'].winfo_children() if isinstance(w, tk.Label)]
    assert any('找不到 system_tasks.xml' in text for text in labels)
    switch(app, 'tasks')
    app.start()
    assert [b[0] for b in boxes] == ['showwarning']


# ========== 問題清單（FR-36、設計第 6.3 節） ==========

def test_problem_window_is_shown_and_copyable(root, tmp_path):
    problems = [Problem('error', 'software.xml', 'vc', 'successCodes 格式錯誤'),
                Problem('warning', 'software.xml', None, '不認得的屬性'),
                Problem('warning', 'tasks\\old.cmd', None, '沒有登記')]
    app = build(root, make_load(tmp_path, problems=problems))

    window = app.problem_window
    assert window.window.winfo_exists()
    assert '3 筆' in window.window.title()
    text = window.box.get('1.0', 'end')
    assert text.index('【software.xml】') < text.index('[錯誤] vc：successCodes 格式錯誤') < text.index('【tasks\\old.cmd】')
    window.copy()
    assert root.clipboard_get() == window.text


def test_no_problem_window_without_problems(root, tmp_path):
    app = build(root, make_load(tmp_path))
    assert not hasattr(app, 'problem_window')


def test_fatal_message_shows_expected_layout():
    message = gui.fatal_message([Problem('fatal', 'software.xml', None, '找不到 software.xml：D:\\x')],
                                Path('D:\\'), 'helper.exe')
    assert '找不到 software.xml' in message
    assert 'helper.exe' in message and 'helper_software\\software.xml' in message and 'Helper' in message


# ========== 全選、全不選（FR-33） ==========

def test_select_buttons_affect_only_the_current_tab(root, tmp_path):
    app = build(root, make_load(tmp_path))
    app.select_none()
    assert not any(r.var.get() for r in app.rows['software'].values())
    assert all(r.var.get() for r in app.rows['tasks'].values())
    switch(app, 'tasks')
    app.select_none()
    app.select_all()
    assert all(r.var.get() for r in app.rows['tasks'].values())
    assert not any(r.var.get() for r in app.rows['software'].values())


# ========== 執行 ==========

def test_start_runs_selected_items_in_order(root, tmp_path, boxes):
    run = FakeRun()
    app = build(root, make_load(tmp_path), run)
    app.rows['software']['b'].var.set(False)

    app.start()
    assert app.running and str(app.buttons['start'].cget('state')) == 'disabled'
    wait_until_idle(root, app)

    [call] = run.calls
    assert call['mode'] == 'software' and call['ids'] == ['a', 'c'] and call['timeout'] == 1000
    assert str(app.buttons['start'].cget('state')) == 'normal'
    assert str(app.buttons['pause'].cget('state')) == 'disabled'


def test_tasks_tab_runs_tasks_with_task_timeout(root, tmp_path, boxes):
    run = FakeRun()
    app = build(root, make_load(tmp_path), run)
    switch(app, 'tasks')
    app.start()
    wait_until_idle(root, app)
    assert run.calls[0]['mode'] == 'tasks' and run.calls[0]['ids'] == ['p1', 'p2', 's1']
    assert run.calls[0]['timeout'] == 300


def test_nothing_selected(root, tmp_path, boxes):
    run = FakeRun()
    app = build(root, make_load(tmp_path), run)
    app.select_none()
    app.start()
    assert run.calls == [] and [b[0] for b in boxes] == ['showwarning']


def test_status_text_next_to_each_item(root, tmp_path, boxes):
    """FR-34：成功代碼不是 0 時顯示代碼（設計第 7.2 節）"""
    run = FakeRun({'a': ('success', 3010), 'b': ('failed', 2), 'c': ('timeout', None)})
    app = build(root, make_load(tmp_path), run)
    app.start()
    wait_until_idle(root, app)
    labels = {i: r.label.cget('text') for i, r in app.rows['software'].items()}
    assert labels == {'a': '成功（3010）', 'b': '失敗（2）', 'c': '逾時'}


LONG = '範例 G：逾時（啟動子程式後一直不結束，30 秒），名稱很長，一直加長到超過半個清單的寬度'


def assert_status_visible(app, mode, ids):
    for item_id in ids:
        label = app.rows[mode][item_id].label
        canvas = label
        while not isinstance(canvas, tk.Canvas):
            canvas = canvas.master
        assert label.winfo_ismapped(), f'{item_id} 的狀態沒有顯示'
        assert label.winfo_width() >= label.winfo_reqwidth(), f'{item_id} 的狀態被壓縮'
        right = label.winfo_rootx() + label.winfo_width()
        assert right <= canvas.winfo_rootx() + canvas.winfo_width(), f'{item_id} 的狀態超出清單的可見範圍'


def test_status_stays_visible_with_long_names(root, tmp_path, boxes):
    """T44 驗收發現：右欄的名稱很長時，執行中的狀態文字被擠到清單的可見範圍外（FR-34）"""
    load = make_load(tmp_path, software=('a', 'b', 'c', 'd'))
    load = dataclasses.replace(load, software=tuple(
        dataclasses.replace(s, name=LONG if s.id in ('c', 'd') else s.name) for s in load.software))
    root.deiconify()  # 版面要真的顯示才算得出位置
    app = build(root, load, FakeRun({'c': ('timeout', None), 'd': ('copy_failed', None)}))
    app.start()
    wait_until_idle(root, app)
    root.update()
    assert_status_visible(app, 'software', ['a', 'b', 'c', 'd'])


def test_wrap_ignores_one_pixel_changes(root, tmp_path, boxes):
    """T44 修正時發現：兩欄平分寬度時，奇數的那一個像素會隨內容在兩欄之間移動（432、433 交替）；
    換行寬度跟著改又會改變內容，真實的 20 個軟體因此無限循環、介面卡住。只差幾個像素時不重設"""
    app = build(root, make_load(tmp_path, software=('a',)))
    row = app.rows['software']['a']
    frame = row.name.master
    frame.event_generate('<Configure>', width=432, height=30)
    first = row.name.cget('wraplength')
    frame.event_generate('<Configure>', width=433, height=30)
    assert row.name.cget('wraplength') == first
    frame.event_generate('<Configure>', width=600, height=30)
    assert row.name.cget('wraplength') != first


def test_task_status_stays_visible_with_long_names(root, tmp_path, boxes):
    load = make_load(tmp_path, categories=[('power', '電源', ['p1', 'p2', 'p3', 'p4'])])
    tasks = tuple(dataclasses.replace(t, name=LONG if t.id in ('p3', 'p4') else t.name, description=LONG)
                  for t in load.categories[0].tasks)
    load = dataclasses.replace(load, categories=(dataclasses.replace(load.categories[0], tasks=tasks),))
    root.deiconify()
    app = build(root, load, FakeRun({'p4': ('failed', 5)}))
    switch(app, 'tasks')
    app.start()
    wait_until_idle(root, app)
    root.update()
    assert_status_visible(app, 'tasks', ['p1', 'p2', 'p3', 'p4'])


def test_progress_states(root, tmp_path):
    app = build(root, make_load(tmp_path))
    row = app.rows['software']['a']
    for state, text in (('waiting', '等待中'), ('copying', '複製中'), ('copied', '已複製'), ('running', '執行中')):
        app._update_row('software', 'a', state, None)
        assert row.label.cget('text') == text
    assert str(row.bar.cget('mode')) == 'indeterminate'  # 執行中是「不確定」模式（DD9）
    app._update_row('software', 'a', 'copy_failed', TaskResult('a', 'copy_failed', None, 0, ''))
    assert row.label.cget('text') == '複製失敗' and row.bar.cget('value') == 100


def test_completion_counts_match_results(root, tmp_path, boxes):
    """FR-51：數量和實際結果一致"""
    run = FakeRun({'b': ('failed', 1)})
    app = build(root, make_load(tmp_path), run)
    app.start()
    wait_until_idle(root, app)
    [(kind, title, message)] = boxes
    assert kind == 'showwarning' and title == '軟體安裝完成'
    assert '成功：2 個' in message and '失敗：1 個' in message
    assert str(logs.log_dir()) in message


def test_all_success_is_info(root, tmp_path, boxes):
    app = build(root, make_load(tmp_path))
    app.start()
    wait_until_idle(root, app)
    assert boxes[0][0] == 'showinfo' and '成功：3 個' in boxes[0][2]


def test_cancelled_items_are_not_counted_as_failures(root, tmp_path, boxes):
    app = build(root, make_load(tmp_path), FakeRun(stop_after=1))
    app.start()
    app.cancel_run()
    wait_until_idle(root, app)
    message = boxes[0][2]
    assert '已取消' in message and '失敗：0 個' in message and '沒有執行：2 個' in message


def test_leftovers_are_listed(root, tmp_path, boxes):
    """FR-48：刪不掉的檔案列在完成對話框"""
    app = build(root, make_load(tmp_path), FakeRun(leftovers=['D:\\stage\\a.exe：使用中']))
    app.start()
    wait_until_idle(root, app)
    assert boxes[0][0] == 'showwarning' and 'D:\\stage\\a.exe：使用中' in boxes[0][2]


def test_aborted_run_shows_reason_and_restores_buttons(root, tmp_path, boxes):
    """FR-47、FR-53：例如空間不足"""
    app = build(root, make_load(tmp_path), FakeRun(aborted='空間不足：需要 20.0 GB'))
    app.start()
    wait_until_idle(root, app)
    assert boxes == [('showerror', '無法執行', '空間不足：需要 20.0 GB')]
    assert str(app.buttons['start'].cget('state')) == 'normal'
    assert '空間不足' in app.status.cget('text')


def test_unexpected_error_restores_buttons(root, tmp_path, boxes):
    """FR-53：執行過程發生非預期錯誤時，介面不可卡在執行中"""
    app = build(root, make_load(tmp_path), FakeRun(raises=RuntimeError('模擬的錯誤')))
    app.start()
    wait_until_idle(root, app)
    assert boxes[0][0] == 'showerror' and 'RuntimeError: 模擬的錯誤' in boxes[0][2]
    assert str(app.buttons['start'].cget('state')) == 'normal'


def test_pause_and_resume(root, tmp_path):
    """FR-43"""
    app = build(root, make_load(tmp_path))
    app._set_running(True)
    app.toggle_pause()
    assert not app.resume.is_set() and app.buttons['pause'].cget('text') == '繼續'
    app.toggle_pause()
    assert app.resume.is_set() and app.buttons['pause'].cget('text') == '暫停'


def test_cancel_also_ends_a_pause(root, tmp_path):
    """FR-44：暫停中按「取消」也要能結束等待"""
    app = build(root, make_load(tmp_path))
    app._set_running(True)
    app.toggle_pause()
    app.cancel_run()
    assert app.cancel.is_set() and app.resume.is_set()
    assert str(app.buttons['cancel'].cget('state')) == 'disabled'


def test_log_folder_button(root, tmp_path, monkeypatch):
    """FR-52：開啟日誌所在的資料夾"""
    folder = tmp_path / 'Desktop' / 'QT_TOOL_LOGS'
    monkeypatch.setattr(logs, 'log_dir', lambda: folder)
    opened = []
    monkeypatch.setattr(gui.os, 'startfile', opened.append, raising=False)
    build(root, make_load(tmp_path)).open_log_folder()
    assert opened == [folder] and folder.is_dir()


def test_closing_while_running_asks_first(root, tmp_path, boxes):
    app = build(root, make_load(tmp_path))
    app._set_running(True)
    app.close()  # askyesno 回答「否」
    assert root.winfo_exists() and boxes[0][0] == 'askyesno'


# ========== 進入點用的函式（T39） ==========

def test_run_opens_the_main_window_until_it_is_closed(root, tmp_path, monkeypatch):
    """helper.py 的第 4、5 步：建立主視窗，執行到關閉為止"""
    shown = []

    class HiddenTk(tk.Tk):
        def __init__(self):
            super().__init__()
            self.withdraw()

        def mainloop(self, n=0):
            shown.append(self.title())
            self.destroy()

    created = []
    real_app = gui.App
    monkeypatch.setattr(gui.tk, 'Tk', HiddenTk)
    monkeypatch.setattr(gui, 'App', lambda r, load, **kw: created.append(kw) or real_app(r, load, **kw))
    gui.run(make_load(tmp_path), is_admin=False)
    assert shown == [gui.WINDOW_TITLE] and created == [{'is_admin': False}]


def test_unhandled_error_in_an_event_is_shown(root, tmp_path, boxes):
    """打包後沒有主控台：事件裡沒有處理的例外要顯示出來，Tk 預設只印到看不到的 stderr（設計第 13 節）"""
    build(root, make_load(tmp_path))

    def broken():
        raise RuntimeError('壞掉了')

    root.after(0, broken)
    root.after(50, root.quit)
    root.mainloop()
    [(kind, title, message)] = boxes
    assert kind == 'showerror' and 'RuntimeError: 壞掉了' in message and 'broken' in message
