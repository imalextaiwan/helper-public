"""讀取 3.0 的兩個設定檔（設計第 4、6 節；FR-14～FR-20、FR-32）

第 6.2 節的每一種狀況至少一個測試：有問題的項目一律略過，並且出現在問題清單，
不可靜默略過（FR-20）。範例資源資料夾是 tests/fixtures/valid（T32）。
"""
import shutil
from pathlib import Path

import pytest

from hpler import config
from hpler.models import Software, SystemTask

REPO = Path(__file__).resolve().parent.parent
FIXTURE = REPO / 'tests' / 'fixtures' / 'valid'


@pytest.fixture
def res(tmp_path):
    """範例資源資料夾的複本，測試可以任意修改"""
    path = tmp_path / 'helper_software'
    shutil.copytree(FIXTURE, path)
    return path


def edit(path, old, new):
    text = path.read_text(encoding='utf-8')
    assert old in text, old
    path.write_text(text.replace(old, new, 1), encoding='utf-8')


def problems(result, severity=None):
    return [p for p in result.problems if severity is None or p.severity == severity]


def only_problem(result, severity):
    """只有一個問題，嚴重度正確；回傳它"""
    assert [p.severity for p in result.problems] == [severity], result.problems
    return result.problems[0]


def software_ids(result):
    return [s.id for s in result.software]


def task_ids(result):
    return [t.id for c in result.categories for t in c.tasks]


# ========== 正常的範例 ==========

def test_example_loads_without_problems(res):
    result = config.load(res)

    assert result.problems == ()
    assert result.resource_dir == res
    assert software_ids(result) == ['cpu_z', 'vcredist', 'sample_desk_tool']  # 保持 XML 的順序
    assert result.software_timeout == 1000
    assert [c.id for c in result.categories] == ['power', 'security']
    assert task_ids(result) == ['power_001', 'security_001']
    assert result.task_timeout == 300


def test_software_fields(res):
    cpu_z, vcredist, desk = config.load(res).software

    assert cpu_z == Software(id='cpu_z', name='CPU-Z', folder=res / 'cpu-z',
                             executable=res / 'cpu-z' / 'setup.exe', args='/S',
                             success_codes=frozenset({0}), copy_first=True, icon=None)
    assert vcredist.success_codes == frozenset({0, 3010})
    assert vcredist.args == '/install /quiet /norestart'
    assert desk.copy_first is False
    assert desk.args == ''  # 沒有 <args>


def test_task_fields(res):
    power, security = config.load(res).categories

    assert power.name == '電源與穩定性優化'
    assert power.tasks == (SystemTask(id='power_001', name='範例：失敗即停',
                                      description='依序執行兩個步驟，任何一步失敗就停止',
                                      script=res / 'tasks' / 'power_001.cmd'),)
    assert security.name == '安全性與存取優化'


@pytest.mark.parametrize('bom', [False, True], ids=['no-bom', 'bom'])
def test_utf8_with_or_without_bom(res, bom):
    """FR-15：記事本存成「UTF-8 含 BOM」也能讀取"""
    for name in ('software.xml', 'system_tasks.xml'):
        data = (res / name).read_bytes()
        (res / name).write_bytes((b'\xef\xbb\xbf' if bom else b'') + data.removeprefix(b'\xef\xbb\xbf'))

    result = config.load(res)
    assert result.problems == ()
    assert len(result.software) == 3 and len(result.categories) == 2


def test_args_kept_verbatim(res):
    """參數原樣保留（第 7.2 節）；只去掉頭尾因排版產生的空白"""
    edit(res / 'software.xml', '<args>/S</args>', '<args>\n      /D=C:\\Program Files\\App  /S\n    </args>')
    assert config.load(res).software[0].args == '/D=C:\\Program Files\\App  /S'


def test_xml_escapes(res):
    edit(res / 'software.xml', '<args>/S</args>', '<args>/S &amp; /Q &lt;x&gt;</args>')
    assert config.load(res).software[0].args == '/S & /Q <x>'


# ========== software.xml：整個檔案的問題（fatal） ==========

def test_software_xml_missing(res):
    (res / 'software.xml').unlink()
    result = config.load(res)

    problem = only_problem(result, 'fatal')
    assert problem.file == 'software.xml'
    assert str(res / 'software.xml') in problem.message
    assert result.software == () and result.categories == ()


def test_resource_dir_missing(tmp_path):
    problem = only_problem(config.load(tmp_path / 'helper_software'), 'fatal')
    assert 'software.xml' in problem.message


def test_software_xml_not_well_formed(res):
    edit(res / 'software.xml', '<name>CPU-Z</name>', '<name>CPU-Z</nmae>')
    problem = only_problem(config.load(res), 'fatal')
    assert '第 7 行' in problem.message  # 顯示行號、欄號


def test_software_xml_not_utf8(res):
    """記事本存成 ANSI（Big5）"""
    text = (res / 'software.xml').read_text(encoding='utf-8')
    (res / 'software.xml').write_bytes(text.encode('cp950'))
    problem = only_problem(config.load(res), 'fatal')
    assert 'UTF-8' in problem.message


def test_software_xml_wrong_root(res):
    edit(res / 'software.xml', '<software timeout', '<softwares timeout')
    edit(res / 'software.xml', '</software>', '</softwares>')
    problem = only_problem(config.load(res), 'fatal')
    assert '<software>' in problem.message


# ========== system_tasks.xml：整個檔案的問題 ==========

def test_system_tasks_xml_missing(res):
    """系統設定分頁停用，軟體安裝照常"""
    (res / 'system_tasks.xml').unlink()
    result = config.load(res)

    problem = only_problem(result, 'warning')
    assert problem.file == 'system_tasks.xml'
    assert result.categories == ()
    assert len(result.software) == 3


def test_system_tasks_xml_not_well_formed(res):
    edit(res / 'system_tasks.xml', '</category>', '</categroy>')
    result = config.load(res)

    problem = only_problem(result, 'error')
    assert problem.file == 'system_tasks.xml' and '行' in problem.message
    assert result.categories == () and len(result.software) == 3


def test_system_tasks_xml_wrong_root(res):
    edit(res / 'system_tasks.xml', '<systemTasks timeout', '<tasks timeout')
    edit(res / 'system_tasks.xml', '</systemTasks>', '</tasks>')
    result = config.load(res)
    assert only_problem(result, 'error').file == 'system_tasks.xml'
    assert result.categories == ()


# ========== 軟體項目 ==========

@pytest.mark.parametrize('old, new', [
    ('<name>CPU-Z</name>', ''),
    ('<name>CPU-Z</name>', '<name>  </name>'),
    ('<folder>cpu-z</folder>', ''),
    ('<executable>setup.exe</executable>', ''),
    ('<name>CPU-Z</name>', '<name>CPU-Z</name><name>CPU-Z 2</name>'),     # 必填欄位重複
    (' id="cpu_z"', ''),                                                   # 缺少 id
    ('id="cpu_z"', 'id="CPU-Z"'),                                          # id 不符合規則
    ('<folder>cpu-z</folder>', '<folder>C:\\Tools\\cpu-z</folder>'),       # 絕對路徑
    ('<folder>cpu-z</folder>', '<folder>\\cpu-z</folder>'),
    ('<folder>cpu-z</folder>', '<folder>C:cpu-z</folder>'),
    ('<folder>cpu-z</folder>', '<folder>..\\cpu-z</folder>'),              # 含 ..
    ('<folder>cpu-z</folder>', '<folder>x\\..\\cpu-z</folder>'),
    ('<folder>cpu-z</folder>', '<folder>.</folder>'),
    ('<executable>setup.exe</executable>', '<executable>..\\cpu-z\\setup.exe</executable>'),  # 含路徑
    ('<executable>setup.exe</executable>', '<executable>missing.exe</executable>'),           # 找不到執行檔（DD4）
    ('successCodes="0,3010"', 'successCodes="0;3010"'),                    # 不套用預設值，略過
    ('successCodes="0,3010"', 'successCodes="0, 3010"'),
], ids=['no-name', 'blank-name', 'no-folder', 'no-executable', 'dup-name', 'no-id', 'bad-id',
        'abs-folder', 'root-folder', 'drive-folder', 'dotdot', 'inner-dotdot', 'dot-folder',
        'exe-path', 'exe-missing', 'codes-semicolon', 'codes-space'])
def test_bad_software_item_is_skipped_and_reported(res, old, new):
    edit(res / 'software.xml', old, new)
    result = config.load(res)

    problem = only_problem(result, 'error')
    assert problem.file == 'software.xml'
    assert len(result.software) == 2  # 其他項目照常載入


def test_duplicate_id_keeps_the_first(res):
    edit(res / 'software.xml', 'id="vcredist"', 'id="cpu_z"')
    result = config.load(res)

    problem = only_problem(result, 'error')
    assert problem.item_id == 'cpu_z'
    assert software_ids(result) == ['cpu_z', 'sample_desk_tool']
    assert result.software[0].name == 'CPU-Z'


def test_missing_executable_names_the_path(res):
    (res / 'cpu-z' / 'setup.exe').unlink()
    problem = only_problem(config.load(res), 'error')
    assert problem.item_id == 'cpu_z'
    assert str(res / 'cpu-z' / 'setup.exe') in problem.message


def test_bad_copy_first_uses_default(res):
    edit(res / 'software.xml', 'copyFirst="false"', 'copyFirst="no"')
    result = config.load(res)

    assert only_problem(result, 'error').item_id == 'sample_desk_tool'
    assert result.software[2].copy_first is True  # 改用預設值，項目照常載入


@pytest.mark.parametrize('value', ['0', '-5', 'abc', '1.5', ''])
def test_bad_timeout_uses_default(res, value):
    edit(res / 'software.xml', 'timeout="1000"', f'timeout="{value}"')
    edit(res / 'system_tasks.xml', 'timeout="300"', f'timeout="{value}"')
    result = config.load(res)

    assert [p.severity for p in result.problems] == ['error', 'error']
    assert result.software_timeout == result.task_timeout == config.DEFAULT_TIMEOUT == 300
    assert len(result.software) == 3 and len(result.categories) == 2


def test_timeout_defaults_to_300(res):
    edit(res / 'software.xml', ' timeout="1000"', '')
    assert config.load(res).software_timeout == 300


@pytest.mark.parametrize('old, new', [
    ('<args>/S</args>', '<arg>/S</arg>'),                                   # 拼錯選填欄位：參數會被忽略
    ('<args>/S</args>', '<args>/S</args><icon>icon.png</icon>'),            # 圖示不寫在 XML
    ('id="cpu_z"', 'id="cpu_z" copyfirst="false"'),                         # 屬性大小寫錯
    ('<software timeout="1000"', '<software timeout="1000" retries="3"'),
    ('</software>', '<group/></software>'),
], ids=['typo-args', 'icon-element', 'typo-attribute', 'root-attribute', 'root-element'])
def test_unknown_fields_are_reported_as_warnings(res, old, new):
    edit(res / 'software.xml', old, new)
    result = config.load(res)

    assert only_problem(result, 'warning').file == 'software.xml'
    assert len(result.software) == 3  # 只忽略該欄位，項目照常載入


def test_schema_location_attribute_is_not_unknown(res):
    """範例的根元素帶有 xsi:noNamespaceSchemaLocation，不算不認得的屬性"""
    assert 'noNamespaceSchemaLocation' in (res / 'software.xml').read_text(encoding='utf-8')
    assert config.load(res).problems == ()


@pytest.mark.parametrize('names, expected', [
    (['icon.png'], 'icon.png'),
    (['icon.gif', 'icon.jpg'], 'icon.jpg'),
    (['icon.jpeg', 'icon.ico', 'icon.png'], 'icon.ico'),  # 依 ico、png、jpg、jpeg、gif 的順序
], ids=['png', 'jpg-over-gif', 'ico-first'])
def test_icon(res, names, expected):
    """FR-16：子資料夾裡有圖示就使用，XML 不另外設定"""
    for name in names:
        (res / 'cpu-z' / name).write_bytes(b'')
    assert config.load(res).software[0].icon == res / 'cpu-z' / expected


def test_nested_folder(res):
    (res / 'tools').mkdir()
    (res / 'cpu-z').rename(res / 'tools' / 'cpu-z')
    edit(res / 'software.xml', '<folder>cpu-z</folder>', '<folder>tools\\cpu-z</folder>')
    cpu_z = config.load(res).software[0]
    assert cpu_z.executable == res / 'tools' / 'cpu-z' / 'setup.exe'


# ========== 系統設定任務 ==========

@pytest.mark.parametrize('old, new, orphaned_script', [
    ('<name>範例：全部跑完</name>', '', False),                             # 缺少名稱
    # id 寫錯或重複時，tasks\security_001.cmd 也就沒有以正確的 id 登記，一併提醒
    ('id="security_001"', 'id="Security-001"', True),                       # id 不符合規則
    ('id="security_001"', 'id="power_001"', True),                          # id 在整個檔案內重複
], ids=['no-name', 'bad-id', 'dup-id'])
def test_bad_task_is_skipped_and_its_empty_category_hidden(res, old, new, orphaned_script):
    """security 分類只有一個任務：任務被略過（error），分類也不顯示（warning）"""
    edit(res / 'system_tasks.xml', old, new)
    result = config.load(res)

    expected = [('error', 'system_tasks.xml'), ('warning', 'system_tasks.xml')]
    if orphaned_script:
        expected.append(('warning', 'tasks\\security_001.cmd'))
    assert [(p.severity, p.file) for p in result.problems] == expected
    assert [c.id for c in result.categories] == ['power']
    assert task_ids(result) == ['power_001']


def test_missing_script_is_reported(res):
    (res / 'tasks' / 'power_001.cmd').unlink()
    result = config.load(res)

    error = next(p for p in result.problems if p.severity == 'error')
    assert error.item_id == 'power_001' and 'power_001.cmd' in error.message
    assert [c.id for c in result.categories] == ['security']


def test_unregistered_script_is_a_warning(res):
    (res / 'tasks' / 'old_task.cmd').write_bytes(b'@echo off\r\nexit /b 0\r\n')
    result = config.load(res)

    problem = only_problem(result, 'warning')
    assert 'old_task.cmd' in problem.file + problem.message
    assert task_ids(result) == ['power_001', 'security_001']


def test_empty_category_is_hidden(res):
    edit(res / 'system_tasks.xml', '<category id="security"',
         '<category id="empty" name="空的分類"/>\n  <category id="security"')
    result = config.load(res)

    assert only_problem(result, 'warning').item_id == 'empty'
    assert [c.id for c in result.categories] == ['power', 'security']


@pytest.mark.parametrize('old, new', [
    (' name="安全性與存取優化"', ''),
    ('id="security" name', 'id="Security" name'),
    ('id="security" name', 'id="power" name'),
], ids=['no-name', 'bad-id', 'dup-id'])
def test_bad_category_is_skipped(res, old, new):
    edit(res / 'system_tasks.xml', old, new)
    result = config.load(res)

    assert only_problem(result, 'error').file == 'system_tasks.xml'
    assert [c.id for c in result.categories] == ['power']


def test_category_from_xml(res):
    """FR-32：在 XML 新增一個分類，介面就多一個區塊"""
    edit(res / 'system_tasks.xml', '</systemTasks>',
         '  <category id="network" name="網路">\n'
         '    <task id="network_001"><name>新任務</name></task>\n'
         '  </category>\n</systemTasks>')
    (res / 'tasks' / 'network_001.cmd').write_bytes(b'@echo off\r\nexit /b 0\r\n')
    result = config.load(res)

    assert result.problems == ()
    assert [c.name for c in result.categories] == ['電源與穩定性優化', '安全性與存取優化', '網路']
    assert result.categories[2].tasks[0].description == ''  # 說明是選填


# ========== 錯誤處理（設計第 13 節） ==========

def test_unexpected_error_in_one_item_does_not_stop_the_others(res, monkeypatch):
    real = config.find_icon

    def boom(folder):
        if folder.name == 'VCRedist':
            raise RuntimeError('模擬的非預期錯誤')
        return real(folder)

    monkeypatch.setattr(config, 'find_icon', boom)
    result = config.load(res)

    problem = only_problem(result, 'error')
    assert problem.item_id == 'vcredist'
    assert 'RuntimeError: 模擬的非預期錯誤' in problem.message and 'Traceback' in problem.message
    assert software_ids(result) == ['cpu_z', 'sample_desk_tool']
