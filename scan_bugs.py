import pathlib
import re
import ast
import sys

root = pathlib.Path(r"c:\Users\Admin\OneDrive - JMS Advisory Services Private Limited\Desktop\Insight")
skip_prefixes = ("test_", "tests_")
skip_dirs = {"migrations", ".git", "__pycache__", "node_modules", "venv", ".venv"}

silent_except = []
todo_fixme = []
hardcoded_secrets = []
direct_model_update = []

secret_pat = re.compile(r'''(SECRET_KEY|PASSWORD|API_KEY|TOKEN)\s*=\s*['"][^'"]{6,}''', re.IGNORECASE)
todo_pat = re.compile(r"#\s*(TODO|FIXME|HACK|XXX)\b", re.IGNORECASE)
direct_update_pat = re.compile(r"\.objects\.filter\(.+\)\.update\(")

for py_file in root.rglob("*.py"):
    if any(part in skip_dirs for part in py_file.parts):
        continue
    if py_file.name.startswith(skip_prefixes):
        continue
    rel = str(py_file.relative_to(root))
    try:
        src = py_file.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        continue

    lines = src.splitlines()
    for i, line in enumerate(lines, 1):
        if secret_pat.search(line) and "settings" not in rel:
            hardcoded_secrets.append(f"{rel}:{i} -> {line.strip()[:90]}")
        if todo_pat.search(line):
            todo_fixme.append(f"{rel}:{i} -> {line.strip()[:90]}")
        if direct_update_pat.search(line):
            direct_model_update.append(f"{rel}:{i} -> {line.strip()[:90]}")

    try:
        tree = ast.parse(src, str(py_file))
    except SyntaxError:
        continue
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            body = node.body
            if len(body) == 1 and isinstance(body[0], ast.Pass):
                silent_except.append(f"{rel}:{node.lineno}")

print(f"=== SILENT EXCEPTION SWALLOWERS (except ... pass): {len(silent_except)} ===")
for item in silent_except[:20]:
    print(" ", item)
if len(silent_except) > 20:
    print(f"  ... and {len(silent_except)-20} more")

print(f"\n=== HARDCODED SECRETS: {len(hardcoded_secrets)} ===")
for item in hardcoded_secrets[:20]:
    print(" ", item)

print(f"\n=== TODO / FIXME COMMENTS: {len(todo_fixme)} ===")
for item in todo_fixme[:30]:
    print(" ", item)
if len(todo_fixme) > 30:
    print(f"  ... and {len(todo_fixme)-30} more")

print(f"\n=== BULK .update() WITHOUT SIGNALS: {len(direct_model_update)} ===")
for item in direct_model_update[:20]:
    print(" ", item)
if len(direct_model_update) > 20:
    print(f"  ... and {len(direct_model_update)-20} more")
