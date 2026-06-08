import os
import re

def process_file(filepath):
    with open(filepath, 'r') as f:
        content = f.read()

    # Replace 'pending' with 'approval_pending'
    # We only match exactly 'pending' or "pending" as whole words inside quotes
    new_content = re.sub(r"'pending'", "'approval_pending'", content)
    new_content = re.sub(r'"pending"', '"approval_pending"', new_content)

    # Some exceptions we don't want to change (like variable names or text)
    # But since we only replace the quoted strings, it should only hit status literals.
    # What about 'payment_pending'? That won't be matched by 'pending' because it has 'payment_' inside the quotes!
    
    if new_content != content:
        with open(filepath, 'w') as f:
            f.write(new_content)
        print(f"Updated {filepath}")

for root, dirs, files in os.walk('.'):
    # skip venv, migrations, and pycache
    if 'venv' in root or 'migrations' in root or '__pycache__' in root or '.git' in root:
        continue
        
    for file in files:
        if file.endswith('.py') and file != 'replace_pending.py':
            process_file(os.path.join(root, file))

