"""2.0 的 INI 轉成 3.0 的 XML 與 .cmd（設計第 11 節；FR-21、NFR-06）

用法：
    python tools/ini2xml.py <2.0 資源資料夾> <輸出資料夾> [--no-copy-first id,id…]

輸出資料夾必須是新的或空的。產生 software.xml、system_tasks.xml、兩個 XSD、tasks\\<id>.cmd
與轉換報告；軟體子資料夾不複製。轉換後以 config.load 讀回，和 INI 的內容逐欄比對。

結束代碼：0 = 轉換完成（報告裡仍可能有需要人工確認的項目）；1 = 無法轉換，或讀回比對不一致；
2 = 參數錯誤。這個工具不打包進執行檔。
"""
from __future__ import annotations

import argparse
import configparser
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Iterable
from xml.sax.saxutils import escape, quoteattr

# tools\ 不是 hpler 套件的一部分：直接執行時，把 repo 根目錄加進搜尋路徑
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hpler import config  # noqa: E402

SCHEMA_DIR = REPO_ROOT / 'resources' / 'schema'
CONFIG_INI = 'config.ini'
SYSTEM_INI = 'system_optimizations.ini'
REPORT_NAME = 'ini2xml_report.txt'
SCRIPT_ENCODING = 'cp950'  # .cmd 以 Big5 存檔（設計第 4.4 節）
# || 前面不留空白：留空白的話，程式收到的命令列結尾會多一個空白，和 2.0 不同
# （set X=1 會把空白存進變數、echo 會印出來）
STEP_SUFFIX = '|| set "FAILED=1"'
# 2.0 介面上的分類名稱（含「第一類：」「第二類：」），依 2.0 顯示的順序
CATEGORIES = (('power', '第一類：電源與穩定性優化'), ('security', '第二類：安全性與存取優化'))
_ID = re.compile(r'[^a-z0-9_]')


class ConversionError(Exception):
    """無法轉換（結束代碼 1）"""


class UsageError(Exception):
    """參數錯誤（結束代碼 2）"""


@dataclass
class SoftwareEntry:
    section: str
    id: str
    name: str
    folder: str
    executable: str
    args: str
    copy_first: bool = True


@dataclass
class TaskEntry:
    section: str
    id: str
    category: str
    name: str
    description: str
    steps: list[str]  # 轉換後的指令（批次檔模式）


@dataclass
class Result:
    verified: bool
    report: str
    software: list[SoftwareEntry]
    tasks: list[TaskEntry] | None  # 沒有 system_optimizations.ini 時是 None


class Report:
    """依標題分組的轉換報告；只列出有內容的標題"""

    HEADINGS = ('無法轉換的段落與項目', 'id 改名', '設定', '找不到的執行檔', '參數', '含有 % 的指令',
                '使用 wmic 的指令', '會影響後面步驟的指令', '指令裡有換行', '無法以 Big5 儲存的字元', 'copyFirst',
                '讀回比對', '接下來')

    def __init__(self):
        self.items: dict[str, list[str]] = {heading: [] for heading in self.HEADINGS}
        self.summary: list[str] = []

    def add(self, heading: str, *lines: str) -> None:
        self.items[heading].extend(lines)

    def text(self) -> str:
        lines = ['Helper 2.0 → 3.0 設定檔轉換報告（tools/ini2xml.py，設計第 11 節）', '', *self.summary]
        for heading, items in self.items.items():
            if items:
                lines += ['', f'【{heading}】', *items]
        return '\n'.join(lines) + '\n'


# ========== 讀取 INI：和 2.0.1 相同的方式 ==========

class LenientInterpolation(configparser.BasicInterpolation):
    """和 2.0.1 的 helper.py 相同：%% 視為 % 的跳脫；有無法解析的 %（例如 %TEMP%）時，
    保留整個原字串，不拋錯"""

    def before_get(self, parser, section, option, value, defaults):
        try:
            return super().before_get(parser, section, option, value, defaults)
        except configparser.InterpolationError:
            return value


def read_ini(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=LenientInterpolation())
    try:
        parser.read(path, encoding='utf-8-sig')  # 和 2.0.1 相同，含 BOM 也可以
    except UnicodeDecodeError as e:
        raise ConversionError(f'{path.name} 不是 UTF-8 編碼（2.0 也讀不到）。請以 UTF-8 另存後再轉換：{e}') from e
    except configparser.Error as e:
        raise ConversionError(f'{path.name} 的格式錯誤（2.0 也讀不到）：{e}') from e
    return parser


def find_file(folder: Path, name: str) -> Path | None:
    """不分大小寫（真實的資源資料夾裡是 Config.ini；Windows 上 2.0 也讀得到）"""
    return next((p for p in sorted(folder.iterdir()) if p.is_file() and p.name.lower() == name), None)


def make_id(section: str, used: set[str], report: Report) -> str:
    """段落名稱就是 id；不符合 id 規則時轉成小寫，不允許的字元換成 _，重複時加上 _2、_3…"""
    base = _ID.sub('_', section.lower()) or 'item'
    item_id, n = base, 2
    while item_id in used:
        item_id, n = f'{base}_{n}', n + 1
    used.add(item_id)
    if item_id != section:
        report.add('id 改名', f'{section} → {item_id}')
    return item_id


# ========== config.ini ==========

def read_settings(parser: configparser.ConfigParser, report: Report) -> tuple[int | None, str]:
    """[settings]：回傳 (timeout, base_path)。timeout 無法使用時回傳 None，改用 3.0 的預設值"""
    base_path = parser.get('settings', 'base_path', fallback='.')
    if base_path != '.':
        report.add('設定', f'base_path = {base_path}：3.0 取消這個設定（DD7），軟體子資料夾一律直接放在資源資料夾底下。'
                         f'請把 {base_path} 底下的子資料夾移到資源資料夾')
    if parser.has_option('settings', 'log_folder'):
        report.add('設定', f'log_folder = {parser.get("settings", "log_folder")}：沒有轉換。2.0 沒有使用這個設定，'
                         '3.0 的日誌一律寫到桌面的 QT_TOOL_LOGS（設計第 8 節）')
    raw = parser.get('settings', 'timeout', fallback=None)
    if raw is None:
        return None, base_path
    try:
        timeout = int(raw)
    except ValueError:
        timeout = 0
    if timeout <= 0:
        report.add('設定', f'timeout = {raw}：不是正整數，沒有轉換，改用預設值 {config.DEFAULT_TIMEOUT} 秒')
        return None, base_path
    return timeout, base_path


def read_software(parser: configparser.ConfigParser, report: Report) -> list[SoftwareEntry]:
    entries, used = [], set()
    for section in parser.sections():
        if section == 'settings':
            continue
        if not section.startswith('software'):  # 2.0 只讀 software 開頭的段落
            report.add('無法轉換的段落與項目', f'{CONFIG_INI} [{section}]：2.0 不讀這個段落，沒有轉換')
            continue
        name = parser.get(section, 'name', fallback=f'[{section}]').strip() or f'[{section}]'
        subfolder = parser.get(section, 'subfolder', fallback='.')
        executable = parser.get(section, 'executable', fallback='')
        args = parser.get(section, 'args', fallback='')
        if not executable:
            report.add('無法轉換的段落與項目', f'{CONFIG_INI} [{section}]：沒有 executable，2.0 也不顯示，沒有轉換')
            continue
        folder = PureWindowsPath(subfolder)
        if folder.drive or folder.root or not folder.parts or '..' in folder.parts:
            report.add('無法轉換的段落與項目',
                       f'{CONFIG_INI} [{section}]：subfolder = {subfolder}。3.0 的 <folder> 必須是資源資料夾底下的'
                       '子資料夾（設計第 4.2 節），請把軟體移到子資料夾後，手動加進 software.xml')
            continue
        if PureWindowsPath(executable).name != executable:
            report.add('無法轉換的段落與項目',
                       f'{CONFIG_INI} [{section}]：executable = {executable}。3.0 的 <executable> 只寫檔名'
                       '（設計第 4.2 節），請把路徑併進 <folder> 後，手動加進 software.xml')
            continue
        if any(c in args for c in '"\'\\'):
            report.add('參數', f'[{section}] {args}：2.0 以 shlex 拆開參數，3.0 原樣傳遞（DD5）。'
                             '含引號或反斜線時，安裝檔收到的參數可能不同，請確認')
        entries.append(SoftwareEntry(section, make_id(section, used, report), name, subfolder, executable, args))
    return entries


def check_executables(source: Path, base_path: str, software: list[SoftwareEntry], report: Report) -> None:
    """2.0 資源資料夾裡找不到的執行檔：和 2.0 的檢查相同，以 base_path 為準"""
    base = source if base_path == '.' else source / base_path
    for entry in software:
        path = base.joinpath(*PureWindowsPath(entry.folder).parts) / entry.executable
        if not path.is_file():
            report.add('找不到的執行檔', f'[{entry.section}] {path}')


# ========== system_optimizations.ini ==========

def read_tasks(parser: configparser.ConfigParser, report: Report) -> list[TaskEntry]:
    by_category: dict[str, list[TaskEntry]] = {cid: [] for cid, _ in CATEGORIES}
    used: set[str] = set()
    for section in parser.sections():
        if section == 'SYSTEM_OPTIMIZATIONS':  # 2.0 的說明段落
            continue
        category = section.split('_', 1)[0] if '_' in section else ''
        if category not in by_category:  # 和 2.0 相同：只認 power_ 與 security_
            report.add('無法轉換的段落與項目', f'{SYSTEM_INI} [{section}]：2.0 不讀這個段落，沒有轉換')
            continue
        name_desc = parser.get(section, 'name', fallback=f'[{section}]')
        commands = parser.get(section, 'commands', fallback='')
        if not commands:
            report.add('無法轉換的段落與項目', f'{SYSTEM_INI} [{section}]：沒有 commands，2.0 也不顯示，沒有轉換')
            continue
        # 和 2.0 相同：以第一個逗號切成名稱與說明
        name, _, description = name_desc.partition(',')
        name = name.strip() or f'[{section}]'
        steps = [convert_command(section, command.strip(), report)
                 for command in commands.split('|') if command.strip()]
        by_category[category].append(TaskEntry(section, make_id(section, used, report), category, name,
                                                description.strip(), steps))
    return [task for cid, _ in CATEGORIES for task in by_category[cid]]


def convert_command(section: str, command: str, report: Report) -> str:
    """2.0 以 cmd /c 執行的一條指令，轉成 .cmd 裡的一行，並把需要人工確認的地方寫進報告"""
    if '\n' in command:  # cmd /c 遇到換行就停止，2.0 只執行第一行
        first, rest = command.split('\n', 1)
        command = first.rstrip()
        dropped = ' / '.join(line.strip() for line in rest.split('\n') if line.strip())
        report.add('指令裡有換行', f'[{section}] 2.0 只執行第一行「{command}」，沒有執行：{dropped}。'
                                   '轉換後也只有第一行；需要的話，請用 | 分開後重新轉換')
    batch, notes = to_batch(command)
    if notes:
        report.add('含有 % 的指令', f'[{section}] {command}', *(f'    {note}' for note in notes))
    if re.search(r'(?i)\bwmic\b', command):
        report.add('使用 wmic 的指令', f'[{section}] {command}：Windows 11 24H2 起預設停用（設計第 4.4 節），請改寫')
    match = re.match(r'(?i)\s*@?\s*(exit|set|setlocal|endlocal|cd|chdir|pushd|popd)\b', command)
    if match:
        effect = ('會結束整個 .cmd，後面的步驟不會執行' if match.group(1).lower() == 'exit'
                  else '會影響同一個 .cmd 後面的步驟')
        report.add('會影響後面步驟的指令', f'[{section}] {command}：2.0 每條指令各自執行；放進 .cmd 之後{effect}')
    bad = sorted({c for c in batch if not _encodable(c)})
    if bad:
        report.add('無法以 Big5 儲存的字元', f'[{section}] {command}：{"、".join(bad)} 以 ? 代替，請修改')
    return batch


def _encodable(char: str) -> bool:
    try:
        char.encode(SCRIPT_ENCODING)
        return True
    except UnicodeEncodeError:
        return False


# ========== % 的轉換：命令列模式 → 批次檔模式 ==========

_FOR = re.compile(r'(?i)\bfor\b((?:\s+/[a-z](?:\s+"[^"]*"|\s+[^\s%"/][^\s%"]*)?)*)\s+%([a-z])\s+in\b')
_ENV = re.compile(r'%[A-Za-z_][A-Za-z0-9_#$\'()*+,\-.?@\[\]`{}~]*(?::[^%]*)?%')


def for_variables(command: str) -> set[str]:
    """for 迴圈宣告的變數（區分大小寫）；for /f 的 tokens= 會再往後宣告幾個字母"""
    letters = set()
    for match in _FOR.finditer(command):
        options, letter = match.groups()
        count = 1
        tokens = re.search(r'tokens=([^\s"]+)', options, re.IGNORECASE)
        if tokens:
            count = 0
            for part in tokens.group(1).split(','):
                part = part.rstrip('*')
                if '-' in part:
                    low, _, high = part.partition('-')
                    count += int(high) - int(low) + 1 if low.isdigit() and high.isdigit() else 1
                elif part:
                    count += 1
            count += tokens.group(1).endswith('*')
        for n in range(max(count, 1)):
            next_letter = chr(ord(letter) + n)
            if next_letter.isalpha() and next_letter.lower() <= 'z':
                letters.add(next_letter)
    return letters


def to_batch(command: str) -> tuple[str, list[str]]:
    """依命令列模式的解析方式由左到右掃描（設計第 11 節）：迴圈變數改成 %%i；%名稱% 保留；
    其他的 % 都是一般字元，改成 %%。回傳 (轉換後的指令, 報告用的說明)"""
    letters = for_variables(command)
    loop = re.compile(r'%(~[fdpnxsatzFDPNXSATZ]*(?:\$[^:%]+:)?)?[' + ''.join(sorted(letters)) + ']') if letters else None
    out, notes, i = [], [], 0
    while i < len(command):
        if command[i] != '%':
            out.append(command[i])
            i += 1
            continue
        match = loop.match(command, i) if loop else None
        if match:
            out.append('%' + match.group(0))
            notes.append(f'迴圈變數 {match.group(0)} → %{match.group(0)}')
        else:
            match = _ENV.match(command, i)
            if match:
                out.append(match.group(0))
                notes.append(f'環境變數 {match.group(0)}：保留。沒有定義時，2.0 會原樣保留，.cmd 裡會變成空字串')
            else:
                out.append('%%')
                notes.append('一般的 % → %%')
                i += 1
                continue
        i = match.end()
    return ''.join(out), list(dict.fromkeys(notes))


# ========== 輸出 ==========

def script_text(task_id: str, section: str, steps: list[str]) -> str:
    """「全部跑完」範本（設計附錄 A；resources/templates/run_all.cmd），CRLF"""
    lines = ['@echo off',
             'rem Helper system task: run every step, fail if any step failed',
             f'rem File name: {task_id}.cmd / ASCII or ANSI / CRLF line endings',
             f'rem Converted from {SYSTEM_INI} [{section}] by tools/ini2xml.py',
             'setlocal',
             'set "FAILED=0"',
             '',
             *(step + STEP_SUFFIX for step in steps),
             '',
             'exit /b %FAILED%']
    return '\r\n'.join(lines) + '\r\n'


def _root(tag: str, schema: str, timeout: int | None, source: str) -> list[str]:
    indent = ' ' * (len(tag) + 2)
    return ['<?xml version="1.0" encoding="utf-8"?>',
            f'<!-- 由 tools/ini2xml.py 從 2.0 的 {source} 轉換（設計第 11 節） -->',
            f'<{tag}' + (f' timeout="{timeout}"' if timeout else ''),
            f'{indent}xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"',
            f'{indent}xsi:noNamespaceSchemaLocation="{schema}">']


def software_xml(entries: list[SoftwareEntry], timeout: int | None) -> str:
    lines = _root('software', 'software.xsd', timeout, CONFIG_INI)
    for e in entries:
        lines.append(f'  <item id={quoteattr(e.id)}' + ('' if e.copy_first else ' copyFirst="false"') + '>')
        lines += [f'    <name>{escape(e.name)}</name>',
                  f'    <folder>{escape(e.folder)}</folder>',
                  f'    <executable>{escape(e.executable)}</executable>']
        if e.args:
            lines.append(f'    <args>{escape(e.args)}</args>')
        lines.append('  </item>')
    lines.append('</software>')
    return '\n'.join(lines) + '\n'


def system_tasks_xml(tasks: list[TaskEntry], timeout: int | None) -> str:
    lines = _root('systemTasks', 'system_tasks.xsd', timeout, SYSTEM_INI)
    for category_id, category_name in CATEGORIES:
        members = [t for t in tasks if t.category == category_id]
        if not members:  # 沒有任務的分類不寫，避免啟動時出現提醒
            continue
        lines.append(f'  <category id="{category_id}" name={quoteattr(category_name)}>')
        for t in members:
            lines += [f'    <task id={quoteattr(t.id)}>', f'      <name>{escape(t.name)}</name>']
            if t.description:
                lines.append(f'      <description>{escape(t.description)}</description>')
            lines.append('    </task>')
        lines.append('  </category>')
    lines.append('</systemTasks>')
    return '\n'.join(lines) + '\n'


def write_output(output: Path, software: list[SoftwareEntry], tasks: list[TaskEntry] | None,
                 timeout: int | None) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / config.SOFTWARE_XML).write_text(software_xml(software, timeout), encoding='utf-8', newline='\r\n')
    shutil.copyfile(SCHEMA_DIR / 'software.xsd', output / 'software.xsd')
    if tasks is None:
        return
    (output / config.SYSTEM_TASKS_XML).write_text(system_tasks_xml(tasks, timeout), encoding='utf-8',
                                                  newline='\r\n')
    shutil.copyfile(SCHEMA_DIR / 'system_tasks.xsd', output / 'system_tasks.xsd')
    (output / config.TASKS_DIR).mkdir()
    for t in tasks:
        (output / config.TASKS_DIR / f'{t.id}.cmd').write_bytes(
            script_text(t.id, t.section, t.steps).encode(SCRIPT_ENCODING, errors='replace'))


# ========== 讀回比對 ==========

def verify(output: Path, software: list[SoftwareEntry], tasks: list[TaskEntry] | None,
           timeout: int | None) -> list[str]:
    """以 config.load 讀回輸出，和 INI 的內容逐欄比對；回傳不一致的地方。
    輸出資料夾沒有軟體子資料夾，所以在暫存資料夾放同名的空檔案代替執行檔"""
    with tempfile.TemporaryDirectory(prefix='ini2xml_') as tmp:
        root = Path(tmp)
        shutil.copytree(output, root, dirs_exist_ok=True)
        for e in software:
            folder = root.joinpath(*PureWindowsPath(e.folder).parts)
            folder.mkdir(parents=True, exist_ok=True)
            (folder / e.executable).touch()
        load = config.load(root)
        mismatches = [f'[{p.severity}] {p.file} {p.item_id or ""}：{p.message}' for p in load.problems
                      if not (tasks is None and p.file == config.SYSTEM_TASKS_XML)]
        mismatches += _compare_software(root, load, software, timeout)
        if tasks is not None:
            mismatches += _compare_tasks(root, load, tasks, timeout)
    return mismatches


def _compare_software(root, load, software, timeout) -> list[str]:
    mismatches = []
    if load.software_timeout != (timeout or config.DEFAULT_TIMEOUT):
        mismatches.append(f'{config.SOFTWARE_XML} 的 timeout：讀回 {load.software_timeout}')
    loaded = {s.id: s for s in load.software}
    if [s.id for s in load.software] != [e.id for e in software]:
        mismatches.append(f'{config.SOFTWARE_XML} 的項目：讀回 {[s.id for s in load.software]}，'
                          f'應該是 {[e.id for e in software]}')
    for e in software:
        s = loaded.get(e.id)
        if s is None:
            continue
        want = (e.name, root.joinpath(*PureWindowsPath(e.folder).parts), e.executable, e.args, e.copy_first,
                frozenset({0}))
        got = (s.name, s.folder, s.executable.name, s.args, s.copy_first, s.success_codes)
        if got != want:
            mismatches.append(f'{e.id}：讀回 {got}，應該是 {want}')
    return mismatches


def _compare_tasks(root, load, tasks, timeout) -> list[str]:
    mismatches = []
    if load.task_timeout != (timeout or config.DEFAULT_TIMEOUT):
        mismatches.append(f'{config.SYSTEM_TASKS_XML} 的 timeout：讀回 {load.task_timeout}')
    want_categories = [(cid, name, [t.id for t in tasks if t.category == cid]) for cid, name in CATEGORIES]
    want_categories = [c for c in want_categories if c[2]]
    got_categories = [(c.id, c.name, [t.id for t in c.tasks]) for c in load.categories]
    if got_categories != want_categories:
        mismatches.append(f'{config.SYSTEM_TASKS_XML} 的分類：讀回 {got_categories}，應該是 {want_categories}')
    loaded = {t.id: t for c in load.categories for t in c.tasks}
    for t in tasks:
        task = loaded.get(t.id)
        if task is None:
            continue
        if (task.name, task.description) != (t.name, t.description):
            mismatches.append(f'{t.id}：讀回 {(task.name, task.description)}，應該是 {(t.name, t.description)}')
        data = task.script.read_bytes()
        if b'\n' in data.replace(b'\r\n', b''):
            mismatches.append(f'{t.id}.cmd：有只用 LF 的換行')
        lines = data.decode(SCRIPT_ENCODING).split('\r\n')
        got = [line[:-len(STEP_SUFFIX)] for line in lines if line.endswith(STEP_SUFFIX)]
        want = [s.encode(SCRIPT_ENCODING, errors='replace').decode(SCRIPT_ENCODING) for s in t.steps]
        if got != want:
            mismatches.append(f'{t.id}.cmd 的指令：讀回 {got}，應該是 {want}')
    return mismatches


# ========== 轉換 ==========

def convert(source: Path, output: Path, *, no_copy_first: Iterable[str] = ()) -> Result:
    source, output = Path(source), Path(output)
    if not source.is_dir():
        raise ConversionError(f'找不到 2.0 的資源資料夾：{source}')
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ConversionError(f'輸出資料夾必須是新的或空的，避免覆蓋檔案：{output}')

    report = Report()
    config_ini = find_file(source, CONFIG_INI)
    if config_ini is None:
        raise ConversionError(f'找不到 {CONFIG_INI}：{source}')
    parser = read_ini(config_ini)
    if not parser.sections():
        raise ConversionError(f'{config_ini.name} 沒有任何段落（2.0 也會顯示「config.ini 格式錯誤」）')
    timeout, base_path = read_settings(parser, report)
    software = read_software(parser, report)
    check_executables(source, base_path, software, report)

    system_ini = find_file(source, SYSTEM_INI)
    tasks = read_tasks(read_ini(system_ini), report) if system_ini else None

    no_copy = [i.strip() for i in no_copy_first if i.strip()]
    unknown = [i for i in no_copy if not any(i in (e.id, e.section) for e in software)]
    if unknown:
        raise UsageError(f'--no-copy-first 的 id 不在轉換後的軟體清單裡：{", ".join(unknown)}')
    for e in software:
        e.copy_first = not (e.id in no_copy or e.section in no_copy)

    write_output(output, software, tasks, timeout)
    mismatches = verify(output, software, tasks, timeout)

    report.summary += [f'來源：{source}', f'輸出：{output}', f'軟體：{len(software)} 項',
                       '系統設定任務：' + ('沒有 system_optimizations.ini，沒有產生 system_tasks.xml 與 tasks\\'
                                     if tasks is None else
                                     '、'.join(f'{name} {sum(t.category == cid for t in tasks)} 項'
                                              for cid, name in CATEGORIES))]
    no_copy_ids = [e.id for e in software if not e.copy_first]
    report.add('copyFirst', f'copyFirst="false"：{"、".join(no_copy_ids)}' if no_copy_ids else
               '全部都會先複製到暫存資料夾（預設）。會自己把檔案複製到桌面的工具，請以 --no-copy-first 重新轉換（DD14）')
    report.add('讀回比對', *(mismatches or [f'一致：以 config.load 讀回，{len(software)} 個軟體'
                                         + ('' if tasks is None else f'、{len(tasks)} 個任務（含 .cmd 裡的指令）')
                                         + '和 INI 的內容相同']))
    report.add('接下來',
               '1. 逐項確認上面列出的地方',
               '2. 把輸出資料夾裡的 XML、XSD 和 tasks\\ 放進資源資料夾（helper_software\\），和各軟體子資料夾放在一起',
               '3. 每個 .cmd 都要在測試機上以系統管理員身分執行一次（設計第 11 節）')
    text = report.text()
    (output / REPORT_NAME).write_text(text, encoding='utf-8-sig', newline='\r\n')
    return Result(not mismatches, text, software, tasks)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='ini2xml', description='Helper 2.0 的 INI 轉成 3.0 的 XML 與 .cmd（設計第 11 節）')
    parser.add_argument('source', type=Path, help='2.0 的資源資料夾（config.ini 所在的資料夾）')
    parser.add_argument('output', type=Path, help='輸出資料夾，必須是新的或空的')
    parser.add_argument('--no-copy-first', default='', metavar='ID,ID…',
                        help='不先複製到暫存資料夾的軟體（會自己把檔案複製到桌面的工具，DD14）')
    args = parser.parse_args(argv)
    try:
        result = convert(args.source, args.output, no_copy_first=args.no_copy_first.split(','))
    except UsageError as e:
        print(f'參數錯誤：{e}', file=sys.stderr)
        return 2
    except (ConversionError, OSError) as e:
        print(f'無法轉換：{e}', file=sys.stderr)
        return 1
    print(result.report)
    if not result.verified:
        print('讀回比對不一致，請看報告的【讀回比對】', file=sys.stderr)
    return 0 if result.verified else 1


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='replace')  # 主控台的編碼不支援的字元以 ? 代替，不讓報告中斷
    sys.exit(main())
