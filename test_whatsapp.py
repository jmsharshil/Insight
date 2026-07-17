#!/usr/bin/env python
"""
WhatsApp Credential + Sender Test Harness.

Tests both:
  1. Raw Meta Graph API (standalone, no Django)
  2. Our production WhatsAppSender (with pooled session, error normalization)

Usage:
    python test_whatsapp.py
    # Uses real target from .env / settings. Plain-text may fail with 131047
    # (no 24h window) — the script will suggest using a template.

Note: The target number must have messaged your WhatsApp Business account
within the last 24h for plain-text to succeed. Otherwise use approved template.
"""
import os
import sys
import json
import logging
import requests
from datetime import datetime

# Optional Django path (for full sender test)
try:
    import django
    from django.conf import settings
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "insight.settings")
    django.setup()
    DJANGO_AVAILABLE = True
except Exception:
    DJANGO_AVAILABLE = False

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TARGET_NUMBER = "918401611072"  # real test target


def test_raw_api(phone_id: str, access_token: str):
    """Standalone raw requests test (no dependencies)."""
    print("\n=== Raw Meta Graph API Test (Standalone) ===")
    print("Target:", TARGET_NUMBER)
    print("Phone Number ID:", phone_id)
    print("Token prefix:", access_token[:15] + "..." + access_token[-5:])

    message = f"Test from Insight ERP at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}. Credentials validated."

    payload = {
        "messaging_product": "whatsapp",
        "to": TARGET_NUMBER,
        "type": "text",
        "text": {"body": message}
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    url = f"https://graph.facebook.com/v20.0/{phone_id}/messages"

    print("Sending plain-text test message...")
    try:
        response = requests.post(
            url, json=payload, headers=headers, timeout=15
        )
        print("HTTP Status:", response.status_code)
        data = {}
        try:
            data = response.json()
            print("Response:", json.dumps(data, indent=2))
        except ValueError:
            print("Raw response:", response.text)

        if response.status_code == 200:
            print("\n✅ RAW API SUCCESS: Credentials valid. Message sent.")
            return True
        else:
            print("\n❌ RAW API Error.")
            if isinstance(data, dict) and "error" in data:
                err = data["error"]
                code = err.get("code")
                print("Error Code:", code)
                print("Message:", err.get("message"))
                if code == 131047:
                    print("\nNote: 131047 = No active 24h customer window. Use an *approved template* instead.")
                elif code in (21211, 131026):
                    print("\nNote: Invalid phone number format or not registered on WhatsApp.")
            return False
    except Exception as e:
        print("❌ Network/Request Error:", str(e))
        return False


def test_sender():
    """Test the integrated WhatsAppSender class (uses pooled session + normalized errors)."""
    if not DJANGO_AVAILABLE:
        print("❌ Django not available — skipping sender test.")
        return False

    print("\n=== WhatsAppSender Class Test ===")
    try:
        from core.sender import WhatsAppConfig, WhatsAppSender
    except Exception as imp_err:
        print("❌ Could not import WhatsAppSender:", imp_err)
        return False

    phone_id = getattr(settings, "WHATSAPP_PHONE_NUMBER_ID", "")
    access_token = getattr(settings, "WHATSAPP_ACCESS_TOKEN", "")

    if not phone_id or not access_token:
        print("❌ Missing WHATSAPP_* settings from .env")
        return False

    print("Phone ID from settings:", phone_id)
    print("Token prefix:", access_token[:20] + "...")
    print("Target number:", TARGET_NUMBER)

    config = WhatsAppConfig(
        phone_number_id=phone_id,
        access_token=access_token,
    )
    print("✅ Config initialized.")

    message = (
        f"Test WhatsApp message from Insight ERP at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}. "
        "This confirms the sender integration is working."
    )
    print("Message prepared.")

    try:
        print("Initializing pooled WhatsAppSender...")
        with WhatsAppSender(config) as wa:
            print("✅ Sender ready. Sending text message to", TARGET_NUMBER, "...")
            response = wa.send_text(to=TARGET_NUMBER, body=message)
            print("✅ SUCCESS! API Response:", json.dumps(response, indent=2))
            print("Message sent successfully.")
            return True
    except Exception as e:  # WhatsAppAPIError or network
        print("❌ ERROR:", type(e).__name__, "-", str(e))
        if hasattr(e, "error_code"):
            code = getattr(e, "error_code", None)
            print("Meta Error Code:", code)
            if code == 131047:
                print("\n→ Use a template message (see core/sender.py examples).")
            elif code in (100, 131026, 21211):
                print("\n→ Check phone number registration / format.")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("WhatsApp Test Harness")
    print("=" * 50)

    # Load credentials (prefer env, Django settings after setup)
    phone_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
    access_token = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
    if DJANGO_AVAILABLE and hasattr(settings, "WHATSAPP_PHONE_NUMBER_ID"):
        phone_id = settings.WHATSAPP_PHONE_NUMBER_ID or phone_id
        access_token = settings.WHATSAPP_ACCESS_TOKEN or access_token

    if not phone_id or not access_token:
        print("❌ No WhatsApp credentials found in .env or Django settings!")
        print("Add to .env:")
        print("  WHATSAPP_PHONE_NUMBER_ID=479507930369273")
        print("  WHATSAPP_ACCESS_TOKEN=...")
        sys.exit(1)

    success_raw = test_raw_api(phone_id, access_token)
    success_sender = test_sender()

    print("\n" + "=" * 50)
    if success_raw or success_sender:
        print("✅ At least one test passed — credentials appear valid.")
        sys.exit(0)
    else:
        print("❌ Both tests failed. Check errors above (common: 131047 = use template).")
        sys.exit(1)
