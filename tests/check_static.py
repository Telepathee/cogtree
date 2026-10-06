# -*- coding: utf-8 -*-
"""静态检查:全量语法编译 + AST 未定义名扫描(NameError 防线)。"""
import ast
import builtins
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAILS = []

BUILTINS = set(dir(builtins)) | {"__file__", "__name__", "__doc__", "__package__",
                                 "__spec__", "__builtins__", "__debug__", "__path__"}

py_files = sorted(p for p in ROOT.rglob("*.py") if "__pycache__" not in p.parts)
print("== 1. 语法编译 ==")
for py in py_files:
    try:
        compile(py.read_text(encoding="utf-8"), str(py), "exec")
        print("  [达成] compile {}".format(py.relative_to(ROOT)))
    except SyntaxError as e:
        print("  [未达成] compile {}: {}".format(py.relative_to(ROOT), e))
        FAILS.append(str(py))

print("== 2. 未定义名扫描 ==")
for py in py_files:
    tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
    bound = set()

    class Binder(ast.NodeVisitor):
        def visit_Name(self, node):
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                bound.add(node.id)

        def visit_FunctionDef(self, node):
            bound.add(node.name)
            self.generic_visit(node)

        def visit_AsyncFunctionDef(self, node):
            bound.add(node.name)
            self.generic_visit(node)

        def visit_ClassDef(self, node):
            bound.add(node.name)
            self.generic_visit(node)

        def visit_arg(self, node):
            bound.add(node.arg)
            self.generic_visit(node)

        def visit_Import(self, node):
            for a in node.names:
                bound.add((a.asname or a.name).split(".")[0])

        def visit_ImportFrom(self, node):
            for a in node.names:
                bound.add(a.asname or a.name)

        def visit_ExceptHandler(self, node):
            if node.name:
                bound.add(node.name)
            self.generic_visit(node)

        def visit_Global(self, node):
            bound.update(node.names)

        def visit_Nonlocal(self, node):
            bound.update(node.names)

    Binder().visit(tree)
    missing = set()

    class Loader(ast.NodeVisitor):
        def visit_Name(self, node):
            if isinstance(node.ctx, ast.Load) and node.id not in bound \
                    and node.id not in BUILTINS:
                missing.add(node.id)

    Loader().visit(tree)
    if missing:
        print("  [未达成] {}: 未定义名 {}".format(py.relative_to(ROOT), sorted(missing)))
        FAILS.append(str(py))
    else:
        print("  [达成] {}".format(py.relative_to(ROOT)))

print()
if FAILS:
    print("总判定:{} 个文件未达成".format(len(FAILS)))
    sys.exit(1)
print("总判定:全部达成")
