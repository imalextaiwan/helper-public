"""讀取 3.0 的兩個設定檔（設計第 4、6 節；FR-14～FR-20、FR-32）

load(resource_dir) 讀取 software.xml 與 system_tasks.xml，回傳 LoadResult。
有問題的項目一律略過，並記在問題清單（problems），不可靜默略過（FR-20、NFR-05）。

只用標準函式庫（Q6）：程式不讀 XSD。XSD 做不到的檢查，例如執行檔與腳本是否存在，
也在這裡。
"""
import re
import traceback
import xml.etree.ElementTree as ET
from pathlib import Path, PureWindowsPath

from .models import LoadResult, Problem, Software, SystemTask, TaskCategory
from .paths import SOFTWARE_XML

SYSTEM_TASKS_XML = 'system_tasks.xml'
TASKS_DIR = 'tasks'
DEFAULT_TIMEOUT = 300  # 秒（DD6）
ICON_NAMES = ('icon.ico', 'icon.png', 'icon.jpg', 'icon.jpeg', 'icon.gif')  # 依這個順序找（FR-16）

_ID = re.compile(r'[a-z0-9_]+')
_EXIT_CODES = re.compile(r'[0-9]+(,[0-9]+)*')
_XSI = '{http://www.w3.org/2001/XMLSchema-instance}'  # xsi:noNamespaceSchemaLocation 等，不算不認得的屬性


def load(resource_dir: Path) -> LoadResult:
    """讀取資源資料夾裡的兩個設定檔。

    software.xml 有整個檔案的問題時（找不到、不是合法的 XML）為 fatal，
    不再讀 system_tasks.xml；呼叫端應顯示錯誤後結束（FR-14）。
    """
    problems = []
    root = _read_xml(resource_dir / SOFTWARE_XML, 'software', 'fatal', 'fatal', problems)
    if root is None:
        return LoadResult(resource_dir, (), DEFAULT_TIMEOUT, (), DEFAULT_TIMEOUT, tuple(problems))
    _check_unknown(root, {'timeout'}, None, SOFTWARE_XML, None, problems)
    software_timeout = _timeout(root, SOFTWARE_XML, problems)
    software = _load_software(root, resource_dir, problems)

    task_timeout, categories = DEFAULT_TIMEOUT, ()
    # 找不到 system_tasks.xml 只是提醒；檔案有問題時停用系統設定分頁（設計第 6.2 節）
    tasks_root = _read_xml(resource_dir / SYSTEM_TASKS_XML, 'systemTasks', 'warning', 'error', problems)
    if tasks_root is not None:
        _check_unknown(tasks_root, {'timeout'}, None, SYSTEM_TASKS_XML, None, problems)
        task_timeout = _timeout(tasks_root, SYSTEM_TASKS_XML, problems)
        categories = _load_categories(tasks_root, resource_dir, problems)

    return LoadResult(resource_dir, software, software_timeout, categories, task_timeout, tuple(problems))


def find_icon(folder: Path) -> Path | None:
    """子資料夾裡的 icon.*；沒有就是 None（FR-16）"""
    for name in ICON_NAMES:
        if (folder / name).is_file():
            return folder / name
    return None


# ========== 整個檔案 ==========

def _read_xml(path, root_tag, missing_severity, broken_severity, problems):
    """讀取並解析一個設定檔，回傳根元素；有問題時記在 problems 並回傳 None"""
    file = path.name

    def problem(severity, message):
        problems.append(Problem(severity, file, None, message))

    if not path.is_file():
        problem(missing_severity, f'找不到 {file}：{path}')
        return None
    try:
        data = path.read_bytes()
    except OSError as e:
        problem(broken_severity, f'無法讀取 {file}：{e}')
        return None
    try:
        data.decode('utf-8')  # 開頭的 BOM 也是合法的 UTF-8（FR-15）
    except UnicodeDecodeError as e:
        line = data[:e.start].count(b'\n') + 1
        problem(broken_severity, f'{file} 不是 UTF-8 編碼（第 {line} 行）。'
                                 f'請以 UTF-8 儲存：記事本的「另存新檔」，編碼選「UTF-8」')
        return None
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        line, column = e.position
        problem(broken_severity, f'{file} 不是合法的 XML：第 {line} 行第 {column + 1} 欄（{e}）')
        return None
    if root.tag != root_tag:
        problem(broken_severity, f'{file} 的根元素必須是 <{root_tag}>，目前是 <{root.tag}>')
        return None
    return root


def _timeout(root, file, problems):
    value = root.get('timeout')
    if value is None:
        return DEFAULT_TIMEOUT
    if value.strip().isdigit() and int(value) > 0:
        return int(value)
    problems.append(Problem('error', file, None,
                            f'timeout 必須是正整數（秒），目前是「{value}」；改用預設值 {DEFAULT_TIMEOUT} 秒'))
    return DEFAULT_TIMEOUT


def _check_unknown(element, attributes, children, file, item_id, problems):
    """不認得的屬性與子元素：忽略，但列為 warning。例如把 <args> 拼錯時，
    安裝檔會在沒有參數的情況下執行，必須讓維護者知道"""
    for name in element.attrib:
        if name not in attributes and not name.startswith(_XSI):
            problems.append(Problem('warning', file, item_id,
                                    f'<{element.tag}> 有不認得的屬性 {name}，已忽略'))
    if children is not None:
        for child in element:
            if child.tag not in children:
                problems.append(Problem('warning', file, item_id,
                                        f'<{element.tag}> 裡有不認得的元素 <{child.tag}>，已忽略'))


def _text(element, tag, required, file, item_id, problems):
    """子元素的文字（去掉頭尾空白）。必填欄位缺少、空白或重複時記為 error，回傳 None"""
    found = element.findall(tag)
    if len(found) > 1:
        problems.append(Problem('error', file, item_id, f'<{tag}> 重複，已略過這一筆'))
        return None
    text = (found[0].text or '').strip() if found else ''
    if required and not text:
        problems.append(Problem('error', file, item_id, f'缺少 <{tag}>，已略過這一筆'))
        return None
    return text


def _check_id(element, seen, file, problems):
    """id 是否存在、符合規則、不重複；不合格時記為 error，回傳 None"""
    item_id = element.get('id')
    if item_id is None:
        problems.append(Problem('error', file, None, f'<{element.tag}> 缺少 id，已略過這一筆'))
        return None
    if not _ID.fullmatch(item_id):
        problems.append(Problem('error', file, item_id,
                                f'id 只能用小寫英文、數字、底線：「{item_id}」，已略過這一筆'))
        return None
    if item_id in seen:
        problems.append(Problem('error', file, item_id, 'id 重複，已略過這一筆（保留第一筆）'))
        return None
    seen.add(item_id)
    return item_id


# ========== software.xml ==========

def _load_software(root, resource_dir, problems):
    result, seen = [], set()
    for element in root:
        if element.tag != 'item':
            problems.append(Problem('warning', SOFTWARE_XML, None,
                                    f'<software> 裡有不認得的元素 <{element.tag}>，已忽略'))
            continue
        try:
            software = _software_item(element, resource_dir, seen, problems)
        except Exception:  # 邊界：一個項目出錯，不影響其他項目（設計第 13 節）
            problems.append(Problem('error', SOFTWARE_XML, element.get('id'),
                                    f'讀取這一筆時發生非預期的錯誤，已略過：\n{traceback.format_exc()}'))
            continue
        if software is not None:
            result.append(software)
    return tuple(result)


def _software_item(element, resource_dir, seen, problems):
    item_id = _check_id(element, seen, SOFTWARE_XML, problems)
    if item_id is None:
        return None

    def error(message):
        problems.append(Problem('error', SOFTWARE_XML, item_id, message))

    _check_unknown(element, {'id', 'successCodes', 'copyFirst'}, {'name', 'folder', 'executable', 'args'},
                   SOFTWARE_XML, item_id, problems)
    fields = {tag: _text(element, tag, required, SOFTWARE_XML, item_id, problems)
              for tag, required in (('name', True), ('folder', True), ('executable', True), ('args', False))}
    if None in fields.values():
        return None

    folder = PureWindowsPath(fields['folder'])
    if folder.drive or folder.root:
        error(f'<folder> 不可以是絕對路徑：「{fields["folder"]}」，已略過這一筆')
        return None
    if not folder.parts or '..' in folder.parts:
        error(f'<folder> 必須是資源資料夾底下的子資料夾，不可含 ..：「{fields["folder"]}」，已略過這一筆')
        return None
    executable_name = fields['executable']
    if PureWindowsPath(executable_name).name != executable_name or executable_name in ('.', '..'):
        error(f'<executable> 只寫檔名，不含路徑：「{executable_name}」，已略過這一筆')
        return None

    success_codes = frozenset({0})
    codes = element.get('successCodes')
    if codes is not None:
        if not _EXIT_CODES.fullmatch(codes):
            # 不套用預設值，避免把失敗誤判為成功（設計第 6.2 節）
            error(f'successCodes 必須是以逗號分隔的整數，例如 0,3010：「{codes}」，已略過這一筆')
            return None
        success_codes = frozenset(int(code) for code in codes.split(','))

    copy_first = True
    value = element.get('copyFirst')
    if value is not None:
        if value in ('true', 'false'):
            copy_first = value == 'true'
        else:
            error(f'copyFirst 只能是 true 或 false：「{value}」；改用預設值 true')

    folder_path = resource_dir.joinpath(*folder.parts)
    executable = folder_path / executable_name
    if not executable.is_file():
        error(f'找不到執行檔：{executable}；不顯示在清單上')  # DD4
        return None

    return Software(id=item_id, name=fields['name'], folder=folder_path, executable=executable,
                    args=fields['args'], success_codes=success_codes, copy_first=copy_first,
                    icon=find_icon(folder_path))


# ========== system_tasks.xml ==========

def _load_categories(root, resource_dir, problems):
    categories, category_ids, task_ids, declared = [], set(), set(), set()
    for element in root:
        if element.tag != 'category':
            problems.append(Problem('warning', SYSTEM_TASKS_XML, None,
                                    f'<systemTasks> 裡有不認得的元素 <{element.tag}>，已忽略'))
            continue
        # XML 裡寫到的任務都算「有登記」，即使這一筆有問題被略過，也不再提醒腳本沒有登記
        declared.update((task.get('id') or '').lower() for task in element.iter('task'))
        try:
            category = _category(element, resource_dir, category_ids, task_ids, problems)
        except Exception:  # 邊界：一個分類出錯，不影響其他分類
            problems.append(Problem('error', SYSTEM_TASKS_XML, element.get('id'),
                                    f'讀取這個分類時發生非預期的錯誤，已略過：\n{traceback.format_exc()}'))
            continue
        if category is not None:
            categories.append(category)
    _check_unregistered_scripts(resource_dir / TASKS_DIR, declared, problems)
    return tuple(categories)


def _category(element, resource_dir, category_ids, task_ids, problems):
    category_id = _check_id(element, category_ids, SYSTEM_TASKS_XML, problems)
    if category_id is None:
        return None
    name = (element.get('name') or '').strip()
    if not name:
        problems.append(Problem('error', SYSTEM_TASKS_XML, category_id, '分類缺少 name，已略過這個分類'))
        return None
    _check_unknown(element, {'id', 'name'}, {'task'}, SYSTEM_TASKS_XML, category_id, problems)

    tasks = []
    for task_element in element.findall('task'):
        try:
            task = _task(task_element, resource_dir, task_ids, problems)
        except Exception:  # 邊界：一個任務出錯，不影響其他任務
            problems.append(Problem('error', SYSTEM_TASKS_XML, task_element.get('id'),
                                    f'讀取這個任務時發生非預期的錯誤，已略過：\n{traceback.format_exc()}'))
            continue
        if task is not None:
            tasks.append(task)
    if not tasks:
        problems.append(Problem('warning', SYSTEM_TASKS_XML, category_id,
                                f'分類「{name}」沒有可用的任務，不顯示'))
        return None
    return TaskCategory(id=category_id, name=name, tasks=tuple(tasks))


def _task(element, resource_dir, task_ids, problems):
    task_id = _check_id(element, task_ids, SYSTEM_TASKS_XML, problems)
    if task_id is None:
        return None
    _check_unknown(element, {'id'}, {'name', 'description'}, SYSTEM_TASKS_XML, task_id, problems)
    name = _text(element, 'name', True, SYSTEM_TASKS_XML, task_id, problems)
    description = _text(element, 'description', False, SYSTEM_TASKS_XML, task_id, problems)
    if name is None or description is None:
        return None
    script = resource_dir / TASKS_DIR / f'{task_id}.cmd'
    if not script.is_file():
        problems.append(Problem('error', SYSTEM_TASKS_XML, task_id,
                                f'找不到腳本 {TASKS_DIR}\\{task_id}.cmd；不顯示在清單上'))  # DD4
        return None
    return SystemTask(id=task_id, name=name, description=description, script=script)


def _check_unregistered_scripts(tasks_dir, declared, problems):
    """tasks\\ 裡有 .cmd，但 XML 沒有登記：可能是忘了登記，或是應該刪掉的舊檔"""
    if not tasks_dir.is_dir():
        return
    for path in sorted(tasks_dir.iterdir()):
        if path.is_file() and path.suffix.lower() == '.cmd' and path.stem.lower() not in declared:
            problems.append(Problem('warning', f'{TASKS_DIR}\\{path.name}', None,
                                    f'{TASKS_DIR}\\{path.name} 沒有登記在 {SYSTEM_TASKS_XML}，不會執行'))
