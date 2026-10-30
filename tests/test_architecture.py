"""架構檢查（設計第 2.1、2.2、14 節；NFR-04、NFR-05）

以語法樹（ast）讀出每個檔案的 import，不執行任何程式碼，所以沒有 tkinter 的環境也能跑：
- hpler 模組之間只能依第 2.1 節的表往下依賴；hpler/__init__.py（產品名稱、版本號）每個模組都可以使用
- 只有 gui 可以 import tkinter（含會載入 tkinter 的 PIL.ImageTk）
- 只用於型別標註的 import（if TYPE_CHECKING:）執行時不會載入，不算依賴
"""
import ast
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# 設計第 2.1 節的「可以依賴」欄
ALLOWED = {
    'hpler/models.py': set(),
    'hpler/paths.py': set(),
    'hpler/admin.py': set(),
    'hpler/config.py': {'models', 'paths'},
    'hpler/staging.py': {'models', 'paths'},
    'hpler/logs.py': {'paths'},
    'hpler/runner.py': {'models', 'staging', 'logs', 'paths'},
    'hpler/gui.py': {'models', 'config', 'runner', 'logs'},
    'helper.py': {'models', 'paths', 'admin', 'config', 'staging', 'logs', 'runner', 'gui'},
    'tools/ini2xml.py': {'config'},
}
HPLER_MODULES = sorted(p.stem for p in (REPO / 'hpler').glob('*.py') if p.stem != '__init__')
TKINTER = ('tkinter', '_tkinter', 'PIL.ImageTk')


class _Imports(ast.NodeVisitor):
    """記錄執行時會載入的 import：(絕對模組名稱, 匯入的名稱)。略過 if TYPE_CHECKING: 區塊"""

    def __init__(self, package: str | None):
        self.package, self.found = package, []

    def visit_If(self, node):
        test = node.test
        if (isinstance(test, ast.Name) and test.id == 'TYPE_CHECKING') or \
                (isinstance(test, ast.Attribute) and test.attr == 'TYPE_CHECKING'):
            for child in node.orelse:  # else 的部分執行時會載入
                self.visit(child)
        else:
            self.generic_visit(node)

    def visit_Import(self, node):
        self.found += [(alias.name, ()) for alias in node.names]

    def visit_ImportFrom(self, node):
        module = node.module or ''
        if node.level:  # 相對 import：本專案只有 hpler 套件裡使用，最多一層
            assert node.level == 1 and self.package, ast.dump(node)
            module = f'{self.package}.{module}' if module else self.package
        self.found.append((module, tuple(alias.name for alias in node.names)))


def runtime_imports(path: Path) -> list[tuple[str, tuple[str, ...]]]:
    package = 'hpler' if path.parent.name == 'hpler' else None
    visitor = _Imports(package)
    visitor.visit(ast.parse(path.read_text(encoding='utf-8')))
    return visitor.found


def hpler_dependencies(path: Path) -> set[str]:
    """這個檔案在執行時依賴的 hpler 模組（不含 hpler/__init__.py）"""
    deps = set()
    for module, names in runtime_imports(path):
        if module == 'hpler':  # from hpler import config / from . import logs, PRODUCT_NAME
            deps.update(name for name in names if name in HPLER_MODULES)
        elif module.startswith('hpler.'):
            deps.add(module.split('.')[1])
    return deps


def imports_tkinter(path: Path) -> bool:
    for module, names in runtime_imports(path):
        full = [module] + [f'{module}.{name}' for name in names]
        if any(name == t or name.startswith(t + '.') for name in full for t in TKINTER):
            return True
    return False


def project_files() -> list[str]:
    files = [*(REPO / 'hpler').glob('*.py'), REPO / 'helper.py', *(REPO / 'tools').glob('*.py')]
    return sorted(p.relative_to(REPO).as_posix() for p in files)


# ========== 規則本身 ==========

def test_every_file_has_a_rule():
    """新增模組時，要先在設計第 2.1 節（和上面的表）決定它可以依賴什麼"""
    assert set(project_files()) - {'hpler/__init__.py'} == set(ALLOWED)


def test_rules_point_downward():
    """依賴表本身沒有循環：可以排出由下往上的順序"""
    rules = {Path(f).stem: deps for f, deps in ALLOWED.items() if f.startswith('hpler/')}
    done: list[str] = []
    while len(done) < len(rules):
        ready = [m for m, deps in rules.items() if m not in done and deps <= set(done)]
        assert ready, f'依賴表有循環：{ {m: d for m, d in rules.items() if m not in done} }'
        done += sorted(ready)


# ========== 程式符合規則 ==========

@pytest.mark.parametrize('file', sorted(ALLOWED))
def test_dependencies_follow_the_design(file):
    extra = hpler_dependencies(REPO / file) - ALLOWED[file]
    assert not extra, f'{file} 依賴了設計第 2.1 節沒有允許的模組：{sorted(extra)}'


def test_only_gui_imports_tkinter():
    assert [f for f in project_files() if imports_tkinter(REPO / f)] == ['hpler/gui.py']


@pytest.mark.parametrize('file', ['hpler/__init__.py', 'hpler/models.py'])
def test_bottom_layer_uses_only_the_standard_library(file):
    """產品資訊與資料模型在最底層：只用標準函式庫"""
    modules = {module.split('.')[0] for module, _ in runtime_imports(REPO / file)}
    assert modules <= set(sys.stdlib_module_names) | {'__future__'}


# ========== 檢查方式本身 ==========

def test_type_checking_imports_are_not_dependencies():
    """logs 的 models 只用於型別標註（設計第 2.2 節）"""
    source = (REPO / 'hpler' / 'logs.py').read_text(encoding='utf-8')
    assert 'from .models import' in source
    assert 'models' not in hpler_dependencies(REPO / 'hpler' / 'logs.py')


@pytest.mark.parametrize('source, expected', [
    ('from . import gui, PRODUCT_NAME', {'gui'}),
    ('from .runner import run_batch', {'runner'}),
    ('import hpler.config', {'config'}),
    ('from hpler import admin', {'admin'}),
    ('def f():\n    from . import staging', {'staging'}),           # 函式裡的 import 也算
    ('if TYPE_CHECKING:\n    from . import gui\nelse:\n    from . import logs', {'logs'}),
    ('from . import __version__', set()),
])
def test_dependency_detection(tmp_path, source, expected):
    path = tmp_path / 'hpler' / 'sample.py'
    path.parent.mkdir()
    path.write_text(source, encoding='utf-8')
    assert hpler_dependencies(path) == expected


@pytest.mark.parametrize('source, expected', [
    ('import tkinter as tk', True),
    ('from tkinter import messagebox', True),
    ('from PIL import ImageTk', True),
    ('from PIL import Image', False),
    ('import _tkinter', True),
    ('"""說明裡提到 tkinter"""', False),
])
def test_tkinter_detection(tmp_path, source, expected):
    path = tmp_path / 'sample.py'
    path.write_text(source, encoding='utf-8')
    assert imports_tkinter(path) is expected
