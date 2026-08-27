import os
import sys
import json
import requests
from urllib.parse import urlencode

try:
    import django
    from django.conf import settings
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "insight.settings")
    django.setup()
except Exception:
    pass

def fetch_templates():
    phone_id = getattr(settings, "WHATSAPP_PHONE_NUMBER_ID", "")
    access_token = getattr(settings, "WHATSAPP_ACCESS_TOKEN", "")
    
    # We need the WABA ID, we can get it from the phone number details
    waba_url = f"https://graph.facebook.com/v19.0/{phone_id}"
    resp = requests.get(waba_url, headers={"Authorization": f"Bearer {access_token}"})
    print("Phone info:", resp.json())
    waba_id = resp.json().get('error', {}).get('message', 'missing')
    
    # Actually wait, maybe I can just fetch templates from the phone_id? No, we need WABA ID, but phone info doesn't always give it unless we use specific endpoints. Let's just print the raw response.

if __name__ == "__main__":
    fetch_templates()
