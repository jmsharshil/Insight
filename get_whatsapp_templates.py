import os
import sys
import requests
import django

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'insight.settings')
django.setup()
from django.conf import settings

def main():
    print("To fetch your templates directly from Meta, you need your WhatsApp Business Account ID (WABA ID).")
    print("You can find it in the Meta Business Manager -> WhatsApp Manager -> Settings -> WhatsApp Business Account ID.")
    print("Or look in the URL of the WhatsApp Manager (business_id=...).\n")
    
    if len(sys.argv) > 1:
        waba_id = sys.argv[1]
    else:
        waba_id = input("Enter your WhatsApp Business Account ID: ").strip()

    if not waba_id:
        print("No WABA ID provided. Exiting.")
        return
        
    token = getattr(settings, 'WHATSAPP_ACCESS_TOKEN', None)
    if not token:
        print("Error: WHATSAPP_ACCESS_TOKEN is not configured in settings.")
        return
    
    url = f"https://graph.facebook.com/v20.0/{waba_id}/message_templates"
    
    print("\nFetching templates from Meta API...")
    response = requests.get(
        url,
        headers={"Authorization": f"Bearer {token}"},
        params={"limit": 100}
    )
    
    if response.status_code != 200:
        print(f"Error fetching templates: {response.json()}")
        return
        
    data = response.json().get('data', [])
    
    approved_templates = [t for t in data if t.get('status') == 'APPROVED']
    other_templates = [t for t in data if t.get('status') != 'APPROVED']
    
    print(f"\n\u2705 --- APPROVED TEMPLATES ({len(approved_templates)}) ---")
    for t in approved_templates:
        name = t.get('name')
        category = t.get('category')
        lang = t.get('language')
        print(f"  - {name} (Language: {lang}, Category: {category})")
        
    if other_templates:
        print(f"\n\u26a0\ufe0f --- OTHER TEMPLATES ({len(other_templates)}) ---")
        for t in other_templates:
             print(f"  - {t.get('name')} (Status: {t.get('status')}, Language: {t.get('language')})")

if __name__ == "__main__":
    main()
