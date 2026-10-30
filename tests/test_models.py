"""資料模型與產品資訊（設計第 2.1、5 節）

模型是純資料：全部唯讀、沒有邏輯，也不依賴 tkinter 或其他 hpler 模組，
所以讀設定、執行時都不需要建立任何視窗物件。
"""
import dataclasses
import re
from pathlib import Path

import pytest

import hpler
from hpler.models import (
    BatchResult,
    CleanupResult,
    LoadResult,
    Problem,
    Software,
    SystemTask,
    TaskCategory,
    TaskResult,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
RES = Path(r'C:\res')


def sample_models():
    software = Software(id='cpu_z', name='CPU-Z', folder=RES / 'cpu-z', executable=RES / 'cpu-z' / 'setup.exe')
    task = SystemTask(id='power_001', name='高效能電源', description='', script=RES / 'tasks' / 'power_001.cmd')
    category = TaskCategory(id='power', name='電源與穩定性優化', tasks=(task,))
    problem = Problem(severity='error', file='software.xml', item_id='x', message='找不到執行檔')
    result = TaskResult(item_id='cpu_z', status='success', exit_code=0, duration_s=1.5, output='')
    cleanup = CleanupResult(removed=(RES,), leftovers=())
    return [
        software, task, category, problem, result, cleanup,
        LoadResult(resource_dir=RES, software=(software,), software_timeout=300,
                   categories=(category,), task_timeout=300, problems=(problem,)),
        BatchResult(results=(result,), cleanup=cleanup),
    ]


# ========== 模型 ==========

def test_software_defaults():
    s = Software(id='a', name='A', folder=RES / 'a', executable=RES / 'a' / 'setup.exe')
    assert s.args == ''
    assert s.success_codes == frozenset({0})  # 預設只有 0 算成功（DD2）
    assert s.copy_first is True  # 預設先複製到暫存資料夾（DD14）
    assert s.icon is None


def test_batch_result_is_not_aborted_by_default():
    assert BatchResult(results=(), cleanup=CleanupResult(removed=(), leftovers=())).aborted is None


@pytest.mark.parametrize('model', sample_models(), ids=lambda m: type(m).__name__)
def test_models_are_read_only(model):
    field = dataclasses.fields(model)[0].name
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(model, field, None)


@pytest.mark.parametrize('model', sample_models(), ids=lambda m: type(m).__name__)
def test_models_compare_by_value_and_are_hashable(model):
    assert model == dataclasses.replace(model)
    assert len({model, dataclasses.replace(model)}) == 1


# ========== 產品資訊（hpler/__init__.py；設計第 2.4 節、FR-23） ==========

def test_product_name():
    assert hpler.PRODUCT_NAME == 'Helper'  # 3.0.1 以前誤寫為 Hpler


def test_version_is_readable_by_helper_spec():
    """helper.spec 以這個規則從 hpler/__init__.py 讀版本號，寫進 exe 的版本資訊"""
    text = (REPO_ROOT / 'hpler' / '__init__.py').read_text(encoding='utf-8')
    match = re.search(r"^__version__ = '(\d+)\.(\d+)\.(\d+)'$", text, re.MULTILINE)
    assert match is not None
    assert '.'.join(match.groups()) == hpler.__version__


def test_product_name_is_readable_by_helper_spec():
    """helper.spec 以這個規則讀產品名稱，寫進 exe 的產品名稱與描述，不另外寫死"""
    text = (REPO_ROOT / 'hpler' / '__init__.py').read_text(encoding='utf-8')
    match = re.search(r"^PRODUCT_NAME = '([^']+)'$", text, re.MULTILINE)
    assert match is not None and match.group(1) == hpler.PRODUCT_NAME
    spec = (REPO_ROOT / 'helper.spec').read_text(encoding='utf-8')
    assert r"^PRODUCT_NAME = '([^']+)'$" in spec
    assert "StringStruct('ProductName', PRODUCT_NAME)" in spec


def test_build_icon_uses_new_name():
    """打包用的圖示只在 repo 裡，直接改名（設計第 2.4 節）"""
    assert (REPO_ROOT / 'assets' / 'helper_icon.ico').is_file()
    assert not (REPO_ROOT / 'assets' / 'hpler_icon.ico').exists()
    assert "'helper_icon.ico'" in (REPO_ROOT / 'helper.spec').read_text(encoding='utf-8')


@pytest.mark.parametrize('relative', [
    'helper.spec',
    'resources/templates/run_all.cmd',
    'resources/templates/stop_on_error.cmd',
    'resources/schema/software.xsd',
    'resources/schema/system_tasks.xsd',
    'tools/ini2xml.py',
])
def test_user_visible_text_has_no_old_name(relative):
    """使用者看得到的文字不再出現 Hpler：版本資訊、範本與轉換工具輸出的註解、XSD 的說明、轉換報告"""
    assert 'Hpler' not in (REPO_ROOT / relative).read_text(encoding='utf-8')
