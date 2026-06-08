import os
import ast

def find_get_apis(root_dir):
    results = []
    for dirpath, _, filenames in os.walk(root_dir):
        if 'venv' in dirpath or '.venv' in dirpath:
            continue
        for filename in filenames:
            if filename == 'views.py':
                filepath = os.path.join(dirpath, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        tree = ast.parse(f.read(), filename=filepath)
                    for node in ast.walk(tree):
                        if isinstance(node, ast.ClassDef):
                            for item in node.body:
                                if isinstance(item, ast.FunctionDef) and item.name == 'get':
                                    results.append(f"{os.path.relpath(filepath, root_dir)}::{node.name}")
                except Exception as e:
                    print(f"Error parsing {filepath}: {e}")
    return results

if __name__ == '__main__':
    apis = find_get_apis('.')
    for api in apis:
        print(api)
