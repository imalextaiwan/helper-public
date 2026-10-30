"""3.0 的設定檔格式：XSD、範例資源資料夾、.cmd 範本（設計第 4 節、附錄 A；FR-18、FR-19）

XSD 只給編輯器即時檢查用，程式執行時不讀它（Q6）。這裡用 lxml 確認 XSD 和設計一致、
範例符合 XSD；.cmd 依第 4.4 節的撰寫規則檢查，並在 Windows 上實際執行範本。
"""
import re
import subprocess
import sys
from pathlib import Path

import pytest

etree = pytest.importorskip('lxml.etree')

REPO = Path(__file__).resolve().parent.parent
SCHEMA = REPO / 'resources' / 'schema'
TEMPLATES = REPO / 'resources' / 'templates'
EXAMPLE = REPO / 'tests' / 'fixtures' / 'valid'
CMD_EXE = Path(r'C:\Windows\System32\cmd.exe')

windows_only = pytest.mark.skipif(sys.platform != 'win32', reason='需要 Windows 的 cmd.exe')

SOFTWARE = (EXAMPLE / 'software.xml').read_text(encoding='utf-8')
TASKS = (EXAMPLE / 'system_tasks.xml').read_text(encoding='utf-8')


def is_valid(xsd, xml_text):
    schema = etree.XMLSchema(etree.parse(str(SCHEMA / xsd)))
    return schema.validate(etree.fromstring(xml_text.encode('utf-8')))


def mutate(text, old, new):
    assert text.count(old) >= 1, old
    return text.replace(old, new, 1)


# ========== XSD 與範例 ==========

@pytest.mark.parametrize('xsd', ['software.xsd', 'system_tasks.xsd'])
def test_schema_is_a_valid_xsd(xsd):
    etree.XMLSchema(etree.parse(str(SCHEMA / xsd)))


def test_examples_match_schemas():
    assert is_valid('software.xsd', SOFTWARE)
    assert is_valid('system_tasks.xsd', TASKS)


def test_example_executables_and_scripts_exist():
    """範例要能直接拿來測 config（T33）：每個執行檔與 tasks\\<id>.cmd 都存在"""
    root = etree.fromstring(SOFTWARE.encode('utf-8'))
    for item in root.iter('item'):
        assert (EXAMPLE / item.findtext('folder') / item.findtext('executable')).is_file()
    for task in etree.fromstring(TASKS.encode('utf-8')).iter('task'):
        assert (EXAMPLE / 'tasks' / f'{task.get("id")}.cmd').is_file()


@pytest.mark.parametrize('old, new', [
    ('id="vcredist"', 'id="cpu_z"'),                                        # id 重複
    ('id="cpu_z"', 'id="CPU_Z"'),                                           # id 只能用小寫
    ('id="cpu_z"', 'id="cpu-z"'),                                           # id 不能有減號
    ('<name>CPU-Z</name>', ''),                                             # 缺少名稱
    ('<name>CPU-Z</name>', '<name>  </name>'),                              # 名稱是空白
    ('<executable>setup.exe</executable>', ''),                             # 缺少執行檔
    ('<folder>cpu-z</folder>', ''),                                         # 缺少子資料夾
    ('successCodes="0,3010"', 'successCodes="0;3010"'),                     # 成功代碼要以逗號分隔
    ('successCodes="0,3010"', 'successCodes="0,"'),
    ('copyFirst="false"', 'copyFirst="no"'),                                # 只接受 true／false
    ('timeout="1000"', 'timeout="0"'),                                      # 逾時要是正整數
    ('timeout="1000"', 'timeout="long"'),
    ('<folder>cpu-z</folder>', '<folder>C:\\Tools\\cpu-z</folder>'),        # 不可以是絕對路徑
    ('<folder>cpu-z</folder>', '<folder>\\cpu-z</folder>'),
    ('<folder>cpu-z</folder>', '<folder>..\\cpu-z</folder>'),               # 不可含 ..
    ('<folder>cpu-z</folder>', '<folder>tools\\..\\cpu-z</folder>'),
    ('<executable>setup.exe</executable>', '<executable>bin\\setup.exe</executable>'),  # 只寫檔名
    ('<args>/S</args>', '<args>/S</args><icon>icon.png</icon>'),            # 圖示不寫在 XML（FR-16）
    ('id="cpu_z"', 'id="cpu_z" enabled="true"'),                            # 不認得的屬性
], ids=lambda v: v if len(v) < 30 else v[:27] + '...')
def test_software_schema_rejects(old, new):
    assert not is_valid('software.xsd', mutate(SOFTWARE, old, new))


@pytest.mark.parametrize('old, new', [
    ('<name>CPU-Z</name>\n    <folder>cpu-z</folder>', '<folder>cpu-z</folder>\n    <name>CPU-Z</name>'),  # 順序不限
    ('successCodes="0,3010"', 'successCodes="0"'),
    (' timeout="1000"', ''),                                                # timeout 選填，預設 300 秒
    ('copyFirst="false"', 'copyFirst="true"'),
    ('<folder>cpu-z</folder>', '<folder>tools\\cpu-z</folder>'),            # 子資料夾可以有多層
    ('<folder>cpu-z</folder>', '<folder>.hidden</folder>'),
], ids=['any-order', 'single-code', 'no-timeout', 'copy-true', 'nested-folder', 'dot-folder'])
def test_software_schema_accepts(old, new):
    assert is_valid('software.xsd', mutate(SOFTWARE, old, new))


@pytest.mark.parametrize('old, new', [
    ('id="security_001"', 'id="power_001"'),                                # 任務 id 在整個檔案內唯一
    ('id="security"', 'id="power"'),                                        # 分類 id 重複
    (' name="電源與穩定性優化"', ''),                                        # 分類缺少名稱
    ('<name>範例：失敗即停</name>', ''),                                     # 任務缺少名稱
    ('id="power_001"', 'id="Power-001"'),
    ('id="power"', 'id="Power"'),
    ('timeout="300"', 'timeout="-5"'),
    ('</task>', '<script>x.cmd</script></task>'),                           # 腳本位置固定，不寫在 XML
], ids=['dup-task', 'dup-category', 'category-name', 'task-name', 'task-id', 'category-id',
        'timeout', 'script'])
def test_tasks_schema_rejects(old, new):
    assert not is_valid('system_tasks.xsd', mutate(TASKS, old, new))


@pytest.mark.parametrize('old, new', [
    ('<description>依序執行兩個步驟，任何一步失敗就停止</description>', ''),  # 說明選填
    (' timeout="300"', ''),
    ('<category id="security"', '<category id="empty" name="空的分類"/>\n  <category id="security"'),
], ids=['no-description', 'no-timeout', 'empty-category'])
def test_tasks_schema_accepts(old, new):
    assert is_valid('system_tasks.xsd', mutate(TASKS, old, new))


# ========== .cmd 的撰寫規則（設計第 4.4 節） ==========

CMD_FILES = sorted(TEMPLATES.glob('*.cmd')) + sorted((EXAMPLE / 'tasks').glob('*.cmd'))


def test_both_templates_exist():
    assert sorted(p.name for p in TEMPLATES.glob('*.cmd')) == ['run_all.cmd', 'stop_on_error.cmd']


@pytest.mark.parametrize('path', CMD_FILES, ids=lambda p: f'{p.parent.name}/{p.name}')
def test_cmd_follows_writing_rules(path):
    data = path.read_bytes()
    assert data.isascii(), '規則 2：只用英文'
    assert data.count(b'\n') == data.count(b'\r\n'), '規則 3：換行一律 CRLF'
    lines = [l.strip() for l in data.decode('ascii').splitlines() if l.strip()]
    assert lines[0].lower() == '@echo off'
    assert re.fullmatch(r'exit /b (0|%FAILED%)', lines[-1]), '規則 1：以 exit /b 結束'
    assert not any(re.search(r'\b(pause|wmic)\b', l, re.I) for l in lines if not l.lower().startswith('rem')), \
        '規則 5、6：不用 pause、wmic'


# ========== 範本的行為（Windows） ==========

def run_template(tmp_path, template, step1_code):
    """把範本的兩個範例指令換成兩個測試步驟，執行後回傳 (結束碼, 執行過的步驟)"""
    lines = (TEMPLATES / template).read_text(encoding='ascii').splitlines()
    # 記號用 s1、s2：「echo 1>>檔案」會被當成「把 1 號輸出導向檔案」
    steps = iter([f'echo s1>>"%~dp0ran.txt" & cmd /c exit {step1_code}',
                  'echo s2>>"%~dp0ran.txt" & cmd /c exit 0'])
    out = []
    for line in lines:
        if line.startswith('powercfg '):
            command, _, on_fail = line.partition(' || ')
            line = f'{next(steps)} || {on_fail}'
        out.append(line)
    script = tmp_path / template
    script.write_bytes(('\r\n'.join(out) + '\r\n').encode('ascii'))
    # 和 3.0 執行任務的方式相同（設計第 7.3 節）
    result = subprocess.run([str(CMD_EXE), '/d', '/c', str(script)], cwd=tmp_path, capture_output=True)
    ran = (tmp_path / 'ran.txt').read_text().split() if (tmp_path / 'ran.txt').exists() else []
    return result.returncode, ran


@windows_only
@pytest.mark.parametrize('template, step1_code, expected_code, expected_steps', [
    ('stop_on_error.cmd', 0, 0, ['s1', 's2']),
    ('stop_on_error.cmd', 5, 1, ['s1']),        # 第一步失敗：停止，不執行第二步
    ('run_all.cmd', 0, 0, ['s1', 's2']),
    ('run_all.cmd', 5, 1, ['s1', 's2']),        # 第一步失敗：照樣執行第二步，最後回報失敗
], ids=['stop-ok', 'stop-fail', 'all-ok', 'all-fail'])
def test_template_behaviour(tmp_path, template, step1_code, expected_code, expected_steps):
    assert run_template(tmp_path, template, step1_code) == (expected_code, expected_steps)


@windows_only
@pytest.mark.parametrize('task', ['power_001', 'security_001'])
def test_example_tasks_succeed(task):
    script = EXAMPLE / 'tasks' / f'{task}.cmd'
    result = subprocess.run([str(CMD_EXE), '/d', '/c', str(script)], cwd=script.parent, capture_output=True)
    assert result.returncode == 0
