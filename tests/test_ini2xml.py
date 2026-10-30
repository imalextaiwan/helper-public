"""轉換工具 tools/ini2xml.py（設計第 11 節；FR-21、NFR-06）

2.0 的 INI 轉成 3.0 的 XML 與 .cmd。指令從命令列模式（2.0 的 cmd /c）改成批次檔模式，
% 的處理方式不同；Windows 上另外把兩種方式實際執行一次，比對輸出。
"""
import subprocess
import sys
from pathlib import Path

import pytest

from hpler import config
from tools import ini2xml

REPO_ROOT = Path(__file__).resolve().parent.parent
windows_only = pytest.mark.skipif(sys.platform != 'win32', reason='需要 Windows 的 cmd.exe')

CONFIG = r"""[software1]
name = 範例快速設定工具
subfolder = Sample_Settings
executable = Sample_Settings.exe
args =

[software2]
name = 3DMark_8897
subfolder = 3DMark
executable = 3dmark-setup.exe
args = /quiet

[software17]
name = SampleDeskTool(資料會放在桌面\SampleDesk\(資料夾中))
subfolder = SampleDeskTool
executable = SampleDeskTool.exe
args =

[settings]
base_path = .
timeout = 1000
"""

SYSTEM = r"""[SYSTEM_OPTIMIZATIONS]
# Hpler 2.0 系統優化設定文件

[security_001]
name = 停用防火牆,停用所有防火牆設定
commands = netsh advfirewall set allprofiles state off

[power_001]
name = 顯示器/休眠永不關閉,永不進入休眠與關閉顯示器
commands = powercfg -change -monitor-timeout-ac 0|powercfg -change -monitor-timeout-dc 0

[power_007]
name = 顯示桌面系統圖示, 顯示電腦、使用者
commands = powershell -Command "Set-ItemProperty -Path 'HKCU:\Software\X' -Name '{20D04FE0}' -Value 0" |
           powershell -Command "Set-ItemProperty -Path 'HKCU:\Software\X' -Name '{59031a47}' -Value 0"
"""

EXECUTABLES = [('Sample_Settings', 'Sample_Settings.exe'), ('3DMark', '3dmark-setup.exe'),
               ('SampleDeskTool', 'SampleDeskTool.exe')]


def make_source(tmp_path, config_ini=CONFIG, system_ini=SYSTEM, executables=EXECUTABLES, *, encoding='utf-8'):
    """2.0 的資源資料夾：兩個 INI 和各軟體的執行檔（空檔案）"""
    source = tmp_path / 'Helper'
    source.mkdir()
    if config_ini is not None:
        (source / 'config.ini').write_text(config_ini, encoding=encoding)
    if system_ini is not None:
        (source / 'system_optimizations.ini').write_text(system_ini, encoding=encoding)
    for folder, executable in executables:
        (source / folder).mkdir(parents=True, exist_ok=True)
        (source / folder / executable).write_bytes(b'')
    return source


def convert(tmp_path, **kwargs):
    source = make_source(tmp_path, **{k: v for k, v in kwargs.items() if k != 'no_copy_first'})
    output = tmp_path / 'out'
    return ini2xml.convert(source, output, no_copy_first=kwargs.get('no_copy_first', ())), output


def load_back(output, executables=EXECUTABLES):
    """以 config.load 讀回輸出；執行檔以空檔案代替（輸出資料夾沒有軟體子資料夾）"""
    for folder, executable in executables:
        (output / folder).mkdir(parents=True, exist_ok=True)
        (output / folder / executable).write_bytes(b'')
    return config.load(output)


def script(output, task_id):
    return (output / 'tasks' / f'{task_id}.cmd').read_bytes()


def steps(output, task_id):
    """.cmd 裡的指令（去掉範本的部分）"""
    lines = script(output, task_id).decode(ini2xml.SCRIPT_ENCODING).split('\r\n')
    return [line[:-len(ini2xml.STEP_SUFFIX)] for line in lines if line.endswith(ini2xml.STEP_SUFFIX)]


# ========== 軟體 ==========

def test_software_items(tmp_path):
    result, output = convert(tmp_path)
    assert result.verified
    load = load_back(output)
    assert load.problems == ()
    assert [(s.id, s.name, s.folder.name, s.executable.name, s.args, s.copy_first) for s in load.software] == [
        ('software1', '範例快速設定工具', 'Sample_Settings', 'Sample_Settings.exe', '', True),
        ('software2', '3DMark_8897', '3DMark', '3dmark-setup.exe', '/quiet', True),
        ('software17', r'SampleDeskTool(資料會放在桌面\SampleDesk\(資料夾中))', 'SampleDeskTool',
         'SampleDeskTool.exe', '', True),
    ]


def test_timeout_goes_to_both_files(tmp_path):
    _, output = convert(tmp_path)
    load = load_back(output)
    assert load.software_timeout == 1000 and load.task_timeout == 1000


def test_empty_args_are_omitted(tmp_path):
    _, output = convert(tmp_path)
    text = (output / 'software.xml').read_text(encoding='utf-8')
    assert text.count('<args>') == 1 and '<args>/quiet</args>' in text


def test_special_characters_are_escaped(tmp_path):
    ini = '[software1]\nname = A & B <測試>\nsubfolder = a&b\nexecutable = setup.exe\nargs = /x="1 & 2"\n'
    result, output = convert(tmp_path, config_ini=ini, executables=[('a&b', 'setup.exe')])
    assert result.verified
    [item] = load_back(output, [('a&b', 'setup.exe')]).software
    assert (item.name, item.folder.name, item.args) == ('A & B <測試>', 'a&b', '/x="1 & 2"')


def test_no_copy_first(tmp_path):
    """DD14：會自己把檔案複製到桌面的工具，不先複製"""
    result, output = convert(tmp_path, no_copy_first=['software17'])
    assert result.verified
    assert {s.id: s.copy_first for s in load_back(output).software} == {
        'software1': True, 'software2': True, 'software17': False}
    assert 'software17' in result.report


def test_no_copy_first_unknown_id(tmp_path):
    with pytest.raises(ini2xml.UsageError, match='nope'):
        convert(tmp_path, no_copy_first=['nope'])
    assert not (tmp_path / 'out').exists()


def test_args_that_2_0_split_differently_are_reported(tmp_path):
    """DD5：2.0 以 shlex 拆開參數，3.0 原樣傳遞；含引號或反斜線時結果可能不同"""
    ini = '[software1]\nname = A\nsubfolder = a\nexecutable = setup.exe\nargs = /D="C:\\Program Files\\A"\n'
    result, _ = convert(tmp_path, config_ini=ini, executables=[('a', 'setup.exe')])
    assert result.verified and 'software1' in result.report and '參數' in result.report


# ========== id ==========

def test_invalid_ids_are_renamed_and_reported(tmp_path):
    ini = ('[software_CPU-Z]\nname = A\nsubfolder = a\nexecutable = a.exe\n'
           '[software_cpu z]\nname = B\nsubfolder = b\nexecutable = b.exe\n')
    result, output = convert(tmp_path, config_ini=ini, executables=[('a', 'a.exe'), ('b', 'b.exe')])
    assert result.verified
    assert [s.id for s in load_back(output, [('a', 'a.exe'), ('b', 'b.exe')]).software] == [
        'software_cpu_z', 'software_cpu_z_2']
    assert 'software_CPU-Z → software_cpu_z' in result.report
    assert 'software_cpu z → software_cpu_z_2' in result.report


# ========== 2.0 本來就不讀的部分 ==========

def test_what_2_0_ignores_is_not_converted_but_reported(tmp_path):
    ini = CONFIG + ('\n[software_noexe]\nname = 沒有執行檔\nsubfolder = x\n'
                    '\n[tools]\nname = 不是 software 開頭\n')
    system = SYSTEM + ('\n[power_empty]\nname = 沒有指令\n'
                       '\n[network_001]\nname = 不認得的分類\ncommands = echo x\n'
                       '\n[nounderscore]\ncommands = echo x\n')
    result, output = convert(tmp_path, config_ini=ini, system_ini=system)
    assert result.verified
    load = load_back(output)
    assert [s.id for s in load.software] == ['software1', 'software2', 'software17']
    assert [t.id for c in load.categories for t in c.tasks] == ['power_001', 'power_007', 'security_001']
    for section in ('software_noexe', 'tools', 'power_empty', 'network_001', 'nounderscore'):
        assert f'[{section}]' in result.report
    assert '[SYSTEM_OPTIMIZATIONS]' not in result.report  # 2.0 的說明段落，不需要提醒


def test_folder_that_3_0_does_not_accept_is_reported(tmp_path):
    """2.0 的 subfolder 預設是 .；3.0 的 <folder> 必須是子資料夾"""
    ini = ('[software1]\nname = A\nexecutable = a.exe\n'
           '[software2]\nname = B\nsubfolder = b\nexecutable = bin\\b.exe\n')
    result, output = convert(tmp_path, config_ini=ini, executables=[('.', 'a.exe'), ('b/bin', 'b.exe')])
    assert result.verified
    assert load_back(output, []).software == ()
    assert '[software1]' in result.report and '[software2]' in result.report


def test_settings_are_reported(tmp_path):
    ini = CONFIG.replace('base_path = .', 'base_path = tools\nlog_folder = logs').replace('timeout = 1000',
                                                                                        'timeout = 10 分鐘')
    result, output = convert(tmp_path, config_ini=ini, executables=[
        (f'tools/{folder}', exe) for folder, exe in EXECUTABLES])
    assert 'base_path' in result.report and 'log_folder' in result.report and 'timeout' in result.report
    assert 'timeout=' not in (output / 'software.xml').read_text(encoding='utf-8')  # 改用預設值


def test_missing_executable_is_reported(tmp_path):
    result, _ = convert(tmp_path, executables=EXECUTABLES[1:])
    assert result.verified
    assert 'Sample_Settings.exe' in result.report


# ========== 系統設定任務 ==========

def test_categories_names_and_descriptions(tmp_path):
    result, output = convert(tmp_path)
    assert result.verified
    load = load_back(output)
    # 和 2.0 介面上的文字相同（設計第 11 節；T44 第 4 項和 2.0.1 對照時確認）
    assert [(c.id, c.name) for c in load.categories] == [('power', '第一類：電源與穩定性優化'),
                                                         ('security', '第二類：安全性與存取優化')]
    tasks = {t.id: t for c in load.categories for t in c.tasks}
    assert [t.id for t in load.categories[0].tasks] == ['power_001', 'power_007']
    assert (tasks['power_001'].name, tasks['power_001'].description) == ('顯示器/休眠永不關閉', '永不進入休眠與關閉顯示器')
    assert (tasks['power_007'].name, tasks['power_007'].description) == ('顯示桌面系統圖示', '顯示電腦、使用者')


def test_name_without_comma_has_no_description(tmp_path):
    system = '[power_001]\nname = 啟用休眠\ncommands = powercfg -h on\n'
    _, output = convert(tmp_path, system_ini=system)
    [category] = load_back(output).categories
    assert (category.tasks[0].name, category.tasks[0].description) == ('啟用休眠', '')


def test_empty_category_is_left_out(tmp_path):
    system = '[power_001]\nname = 啟用休眠\ncommands = powercfg -h on\n'
    _, output = convert(tmp_path, system_ini=system)
    assert '<category id="security"' not in (output / 'system_tasks.xml').read_text(encoding='utf-8')


def test_each_command_is_one_step(tmp_path):
    _, output = convert(tmp_path)
    assert steps(output, 'power_001') == ['powercfg -change -monitor-timeout-ac 0',
                                          'powercfg -change -monitor-timeout-dc 0']
    assert steps(output, 'power_007') == [
        "powershell -Command \"Set-ItemProperty -Path 'HKCU:\\Software\\X' -Name '{20D04FE0}' -Value 0\"",
        "powershell -Command \"Set-ItemProperty -Path 'HKCU:\\Software\\X' -Name '{59031a47}' -Value 0\""]


def test_script_follows_the_run_all_template(tmp_path):
    """「全部跑完」範本（附錄 A）：每個步驟都執行，有任何一步失敗就以 1 結束"""
    _, output = convert(tmp_path)
    data = script(output, 'security_001')
    assert b'\r\n' in data and b'\n' not in data.replace(b'\r\n', b'')  # 只用 CRLF（第 4.4 節）
    template = (REPO_ROOT / 'resources' / 'templates' / 'run_all.cmd').read_text(encoding='ascii').splitlines()
    lines = data.decode(ini2xml.SCRIPT_ENCODING).split('\r\n')
    keep = [line for line in template if not line.endswith(ini2xml.STEP_SUFFIX)]
    generated = [line for line in lines if not line.endswith(ini2xml.STEP_SUFFIX)
                 and not line.startswith('rem Converted')]
    assert generated == [line.replace('<task id>', 'security_001') for line in keep] + ['']
    assert 'netsh advfirewall set allprofiles state off' + ini2xml.STEP_SUFFIX in lines


def test_newline_inside_one_command_keeps_only_the_first_line(tmp_path):
    """cmd /c 遇到換行就停止，2.0 只執行第一行"""
    system = '[power_001]\nname = A\ncommands = echo one\n    echo two | echo three\n'
    result, output = convert(tmp_path, system_ini=system)
    assert result.verified
    assert steps(output, 'power_001') == ['echo one', 'echo three']
    assert 'echo two' in result.report


def test_wmic_is_reported(tmp_path):
    system = '[power_001]\nname = A\ncommands = wmic os get caption|echo ok\n'
    result, _ = convert(tmp_path, system_ini=system)
    assert 'wmic os get caption' in result.report and 'wmic' in result.report


def test_characters_big5_cannot_store_are_reported(tmp_path):
    system = '[power_001]\nname = A\ncommands = echo 中文😀|echo ok\n'
    result, output = convert(tmp_path, system_ini=system)
    assert result.verified
    assert steps(output, 'power_001') == ['echo 中文?', 'echo ok']
    assert '😀' in result.report


def test_without_system_optimizations_ini(tmp_path):
    result, output = convert(tmp_path, system_ini=None)
    assert result.verified
    assert not (output / 'system_tasks.xml').exists() and not (output / 'tasks').exists()
    assert 'system_optimizations.ini' in result.report


# ========== % 的轉換（命令列模式 → 批次檔模式） ==========

@pytest.mark.parametrize('command, expected', [
    ('powercfg -h on', 'powercfg -h on'),
    ('echo 50%', 'echo 50%%'),
    ('echo 50% and 60%', 'echo 50%% and 60%%'),
    ('echo a%%b', 'echo a%%%%b'),                      # 命令列模式的 %% 不是跳脫
    ('echo [%OS%]', 'echo [%OS%]'),
    ('echo [%OS:~0,3%]', 'echo [%OS:~0,3%]'),
    ('echo [%ProgramFiles(x86)%]', 'echo [%ProgramFiles(x86)%]'),
    ('echo [%%OS%%]', 'echo [%%%OS%%%]'),
    ('for %i in (x y) do @echo [%i]', 'for %%i in (x y) do @echo [%%i]'),
    ('for %i in (C:\\a.txt) do @echo [%~ni]', 'for %%i in (C:\\a.txt) do @echo [%%~ni]'),
    ('for /l %i in (1,1,2) do @echo [%i]', 'for /l %%i in (1,1,2) do @echo [%%i]'),
    ('for /f "tokens=1,2 delims=," %a in ("p,q") do @echo [%a][%b]',
     'for /f "tokens=1,2 delims=," %%a in ("p,q") do @echo [%%a][%%b]'),
])
def test_to_batch(command, expected):
    assert ini2xml.to_batch(command)[0] == expected


def test_percent_conversions_are_reported(tmp_path):
    system = '[power_001]\nname = A\ncommands = echo %%TEMP%% 100%%%%\n'  # 2.0 讀到 echo %TEMP% 100%%
    result, output = convert(tmp_path, system_ini=system)
    assert steps(output, 'power_001') == ['echo %TEMP% 100%%%%']
    assert '%TEMP%' in result.report and '空字串' in result.report


def test_ini_is_read_like_2_0(tmp_path):
    """和 2.0.1 相同的插值規則：%% 變成 %；有無法解析的 % 時保留整個原字串"""
    system = ('[power_001]\nname = A\ncommands = echo 50%%|echo b\n'
              '[power_002]\nname = B\ncommands = echo %TEMP% 100%%|echo c\n')
    _, output = convert(tmp_path, system_ini=system)
    assert steps(output, 'power_001') == ['echo 50%%', 'echo b']           # 2.0 執行的是 echo 50%
    assert steps(output, 'power_002') == ['echo %TEMP% 100%%%%', 'echo c']  # 2.0 執行的是 echo %TEMP% 100%%


# 印出自己收到的整個命令列：程式實際收到的內容要和 2.0 完全相同（T41 用替身程式實測時，發現多了結尾的空白）
PRINT_COMMAND_LINE = (f'"{sys.executable}" -c "import ctypes; k = ctypes.windll.kernel32; '
                      f'k.GetCommandLineW.restype = ctypes.c_wchar_p; print(k.GetCommandLineW())" '
                      f'/v X "a b" /f')

SAME_OUTPUT = [
    'echo 50%', 'echo 50% and 60%', 'echo a%%b', 'echo [%OS%]', 'echo [%OS:~0,3%]', 'echo [%%OS%%]',
    'echo [%ProgramFiles%]', 'for %i in (x y) do @echo [%i]', 'for %i in (C:\\Windows\\notepad.exe) do @echo [%~ni]',
    'for /l %i in (1,1,2) do @echo [%i]', 'for /f "tokens=1,2 delims=," %a in ("p,q") do @echo [%a][%b]',
    PRINT_COMMAND_LINE,
]


def run_converted(tmp_path, command):
    path = tmp_path / 'step.cmd'
    path.write_bytes(ini2xml.script_text('power_001', 'power_001', [ini2xml.to_batch(command)[0]])
                     .encode(ini2xml.SCRIPT_ENCODING))
    return subprocess.run(['cmd.exe', '/d', '/c', str(path)], capture_output=True, text=True)


@windows_only
@pytest.mark.parametrize('command', SAME_OUTPUT)
def test_converted_command_prints_the_same_as_2_0(tmp_path, command):
    """2.0 的執行方式（subprocess.run(command, shell=True)）和轉換後的 .cmd，輸出完全相同"""
    before = subprocess.run(command, shell=True, capture_output=True, text=True)
    after = run_converted(tmp_path, command)
    assert after.stdout == before.stdout and before.stdout.strip()


@windows_only
def test_script_exit_code(tmp_path):
    """有任何一步失敗就以 1 結束，但每一步都會執行（和 2.0 相同）"""
    path = tmp_path / 'step.cmd'
    path.write_bytes(ini2xml.script_text('power_001', 'power_001', ['cmd /c exit 3', 'echo still runs'])
                     .encode(ini2xml.SCRIPT_ENCODING))
    result = subprocess.run(['cmd.exe', '/d', '/c', str(path)], capture_output=True, text=True)
    assert result.returncode == 1 and 'still runs' in result.stdout


def test_commands_that_affect_later_steps_are_reported(tmp_path):
    """2.0 每條指令各自以 cmd /c 執行；放進同一個 .cmd 之後，exit 會結束整個腳本，set、cd 會影響後面的步驟"""
    system = '[power_001]\nname = A\ncommands = set X=1|cd C:\\Windows|exit /b 2|echo ok\n'
    result, _ = convert(tmp_path, system_ini=system)
    for command in ('set X=1', 'cd C:\\Windows', 'exit /b 2'):
        assert command in result.report
    assert 'echo ok' not in result.report


# ========== 輸出、讀回比對 ==========

def test_output_files(tmp_path):
    result, output = convert(tmp_path)
    assert sorted(p.name for p in output.iterdir()) == [
        ini2xml.REPORT_NAME, 'software.xml', 'software.xsd', 'system_tasks.xml', 'system_tasks.xsd', 'tasks']
    assert (output / 'software.xsd').read_bytes() == (REPO_ROOT / 'resources' / 'schema' / 'software.xsd').read_bytes()
    assert (output / ini2xml.REPORT_NAME).read_text(encoding='utf-8-sig').replace('\r\n', '\n') == result.report


def test_output_must_be_new_or_empty(tmp_path):
    (tmp_path / 'out').mkdir()
    (tmp_path / 'out' / 'keep.txt').write_text('mine')
    with pytest.raises(ini2xml.ConversionError, match='空'):
        convert(tmp_path)
    assert [p.name for p in (tmp_path / 'out').iterdir()] == ['keep.txt']


def test_read_back_mismatch_fails(tmp_path, monkeypatch):
    real = ini2xml.software_xml
    monkeypatch.setattr(ini2xml, 'software_xml', lambda entries, timeout: real(entries[:-1], timeout))
    result, _ = convert(tmp_path)
    assert not result.verified and 'software17' in result.report


# ========== 無法轉換 ==========

def test_missing_config_ini(tmp_path):
    with pytest.raises(ini2xml.ConversionError, match='config.ini'):
        convert(tmp_path, config_ini=None)


def test_config_ini_name_is_case_insensitive(tmp_path):
    """真實的資源資料夾裡是 Config.ini（Windows 不分大小寫，2.0 也讀得到）"""
    source = make_source(tmp_path, config_ini=None)
    (source / 'Config.ini').write_text(CONFIG, encoding='utf-8')
    assert ini2xml.convert(source, tmp_path / 'out').verified


def test_not_utf8(tmp_path):
    with pytest.raises(ini2xml.ConversionError, match='UTF-8'):
        convert(tmp_path, encoding='cp950')


def test_duplicate_section(tmp_path):
    with pytest.raises(ini2xml.ConversionError, match='software1'):
        convert(tmp_path, config_ini=CONFIG + '\n[software1]\nname = again\n')


# ========== 命令列 ==========

def test_main_exit_codes(tmp_path, capsys):
    source = make_source(tmp_path)
    assert ini2xml.main([str(source), str(tmp_path / 'out')]) == 0
    assert '讀回比對' in capsys.readouterr().out
    assert ini2xml.main([str(source), str(tmp_path / 'out')]) == 1        # 輸出資料夾不是空的
    assert ini2xml.main([str(source), str(tmp_path / 'out2'), '--no-copy-first', 'nope']) == 2
