import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "insight.settings")
django.setup()

from core.utils import _run_whatsapp_send

TARGET_NUMBER = "918401611072"

print("Testing CRM template logger...")
try:
    _run_whatsapp_send(
        method="send_template",
        to=TARGET_NUMBER,
        template_name="otp_verification",
        language_code="en_US",
        components=[{
            "type": "body",
            "parameters": [{"type": "text", "text": "123456"}],
        }],
        fallback_body="Your OTP is 123456"
    )
    print("Success! The Meta API returned successfully, and the CRM logger should have been called.")
except Exception as e:
    import traceback
    traceback.print_exc()
    print(f"Failed: {e}")
