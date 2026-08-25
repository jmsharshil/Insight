import os
import re
import sys
import django
from django.template.loader import get_template
from django.template import TemplateDoesNotExist

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'insight.settings')
django.setup()

def find_html_references(root_dir):
    """Scan all .py files for strings ending in .html"""
    html_files = set()
    pattern = re.compile(r"['\"]([^'\"]+\.html)['\"]")
    
    for dirpath, _, filenames in os.walk(root_dir):
        if 'venv' in dirpath or '.git' in dirpath or '__pycache__' in dirpath:
            continue
            
        for filename in filenames:
            if filename.endswith('.py'):
                filepath = os.path.join(dirpath, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        content = f.read()
                        matches = pattern.findall(content)
                        for match in matches:
                            html_files.add(match)
                except Exception as e:
                    pass
    return html_files

def main():
    print("Scanning for template references in Python files...")
    templates = find_html_references('.')
    
    if not templates:
        print("No template references found in .py files.")
        return

    print(f"Found {len(templates)} unique template references.")
    print("-" * 50)
    
    missing = []
    found = []
    
    for template_name in sorted(templates):
        try:
            get_template(template_name)
            found.append(template_name)
        except TemplateDoesNotExist:
            missing.append(template_name)
            
    print(f"\n\u2705 Found {len(found)} templates that successfully loaded:")
    for t in found:
        print(f"  - {t}")
        
    print(f"\n\u274c Missing {len(missing)} templates (these are referenced in code but do not exist in the templates directory):")
    for t in missing:
        print(f"  - {t}")
        
    if missing:
        print("\nWarning: Some templates are missing!")
        sys.exit(1)
    else:
        print("\nAll referenced templates exist!")
        sys.exit(0)

if __name__ == '__main__':
    main()
