import os
import sys
import json
import logging
from datetime import datetime

try:
    import django
    from django.conf import settings
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "insight.settings")
    django.setup()
    DJANGO_AVAILABLE = True
except Exception:
    DJANGO_AVAILABLE = False
    print("Django not available. Run this within the project.")
    sys.exit(1)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TARGET_NUMBER = "918401611072"

def test_all_templates():
    from core.sender import WhatsAppConfig, WhatsAppSender

    phone_id = getattr(settings, "WHATSAPP_PHONE_NUMBER_ID", "")
    access_token = getattr(settings, "WHATSAPP_ACCESS_TOKEN", "")

    if not phone_id or not access_token:
        print("Missing WHATSAPP_* settings from .env")
        return False

    config = WhatsAppConfig(phone_number_id=phone_id, access_token=access_token)
    
    templates_to_test = [
        {
            "name": "otp_verification",
            "components": [{"type": "body", "parameters": [{"type": "text", "text": "123456"}]}]
        },
        {
            "name": "login_otp",
            "components": [{"type": "body", "parameters": [{"type": "text", "text": "654321"}]}]
        },
        {
            "name": "resend_login_otp",
            "components": [{"type": "body", "parameters": [{"type": "text", "text": "987654"}]}]
        },
        {
            "name": "admission_process",
            "components": [{"type": "body", "parameters": [{"type": "text", "text": "John Doe"}]}]
        },
        {
            "name": "no_one_institute_in_gujarat_",
            "components": [{"type": "body", "parameters": [{"type": "text", "text": "John Doe"}]}]
        }
    ]

    with WhatsAppSender(config) as wa:
        for tpl in templates_to_test:
            print(f"\n--- Testing Template: {tpl['name']} ---")
            try:
                response = wa.send_template(
                    to=TARGET_NUMBER,
                    template_name=tpl["name"],
                    language_code="en",
                    components=tpl.get("components", []),
                )
                print(f"SUCCESS! API Response: {json.dumps(response)}")
            except Exception as e:
                print(f"ERROR: {type(e).__name__} - {str(e)}")
                if hasattr(e, "error_code"):
                    print(f"Meta Error Code: {getattr(e, 'error_code')}")

if __name__ == "__main__":
    test_all_templates()
