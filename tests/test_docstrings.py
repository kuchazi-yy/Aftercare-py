"""通过 AST 强制所有项目 Python 文件和函数包含中文 Docstring。"""

import ast
from pathlib import Path


def has_chinese(text: str) -> bool:
    """判断文本是否至少包含一个中文字符。"""

    return any("\u4e00" <= char <= "\u9fff" for char in text)


def python_files() -> list[Path]:
    """返回源码、脚本和测试目录中的 Python 文件。"""

    roots = [Path("src"), Path("scripts"), Path("tests")]
    return [path for root in roots for path in root.rglob("*.py")]


def test_all_modules_and_functions_have_chinese_docstrings() -> None:
    """检查模块、类、函数和异步函数的中文 Docstring。"""

    missing: list[str] = []
    for path in python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        module_doc = ast.get_docstring(tree) or ""
        if not has_chinese(module_doc):
            missing.append(f"{path}:module")
        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                doc = ast.get_docstring(node) or ""
                if not has_chinese(doc):
                    missing.append(f"{path}:{node.lineno}:{node.name}")
    assert not missing, "缺少中文 Docstring:\n" + "\n".join(missing)
