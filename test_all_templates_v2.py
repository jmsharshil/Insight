import os
import sys
import json
import logging

try:
    import django
    from django.conf import settings
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "insight.settings")
    django.setup()
except Exception:
    pass

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TARGET_NUMBER = "918401611072"

def run():
    from core.sender import WhatsAppConfig, WhatsAppSender
    phone_id = getattr(settings, "WHATSAPP_PHONE_NUMBER_ID", "")
    access_token = getattr(settings, "WHATSAPP_ACCESS_TOKEN", "")
    config = WhatsAppConfig(phone_number_id=phone_id, access_token=access_token)

    templates = [
        {
            "name": "no_one_institute_in_gujarat_",
            "lang": "en_US",
            "components": [{"type": "body", "parameters": [{"type": "text", "text": "John Doe"}]}]
        },
        {
            "name": "no_one_institute_in_gujarat",
            "lang": "en_US",
            "components": [{"type": "body", "parameters": [{"type": "text", "text": "John Doe"}]}]
        },
        {
            "name": "no_one_institute_in_gujarat",
            "lang": "en",
            "components": [{"type": "body", "parameters": [{"type": "text", "text": "John Doe"}]}]
        }
    ]

    with WhatsAppSender(config) as wa:
        for tpl in templates:
            print(f"\n--- Testing Template: {tpl['name']} ({tpl['lang']}) ---")
            try:
                response = wa.send_template(
                    to=TARGET_NUMBER,
                    template_name=tpl["name"],
                    language_code=tpl["lang"],
                    components=tpl["components"],
                )
                print(f"SUCCESS! API Response: {json.dumps(response)}")
                break
            except Exception as e:
                print(f"ERROR: {type(e).__name__} - {str(e)}")

if __name__ == "__main__":
    run()
