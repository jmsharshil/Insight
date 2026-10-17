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

# Phone number with country code for live testing (as used in other tests)
TARGET_NUMBER = "918401611072"

def test_all_meta_templates():
    """Test all WhatsApp/Meta templates used in send_whatsapp_with_fallback calls from emails.py live."""
    from core.sender import WhatsAppConfig, WhatsAppSender

    phone_id = getattr(settings, "WHATSAPP_PHONE_NUMBER_ID", "")
    access_token = getattr(settings, "WHATSAPP_ACCESS_TOKEN", "")

    if not phone_id or not access_token:
        print("Missing WHATSAPP_PHONE_NUMBER_ID or WHATSAPP_ACCESS_TOKEN in settings/.env")
        print("Please configure them to test live Meta templates.")
        return False

    config = WhatsAppConfig(phone_number_id=phone_id, access_token=access_token)
    
    # Templates extracted from send_whatsapp_with_fallback calls in emails.py
    # These match the template_name parameters used with checker_assignment_, etc.
    templates_to_test = [
        {
            "name": "checker_assignment_",
            "components": [{"type": "body", "parameters": [
                {"type": "text", "text": "Test Checker"},
                {"type": "text", "text": "Test Exam Title"},
                {"type": "text", "text": "15 Sep 2025"},
                {"type": "text", "text": "https://example.com/submit?token=abc123"}
            ]}]
        },
        {
            "name": "answer_key_",
            "components": [{"type": "body", "parameters": [
                {"type": "text", "text": "Test Checker"},
                {"type": "text", "text": "Test Exam Title"}
            ]}]
        },
        {
            "name": "submission_reminder_",
            "components": [{"type": "body", "parameters": [
                {"type": "text", "text": "Test Checker"},
                {"type": "text", "text": "Test Exam Title"}
            ]}]
        },
        {
            "name": "material_upload_reminder_",
            "components": [{"type": "body", "parameters": [
                {"type": "text", "text": "Test Faculty"},
                {"type": "text", "text": "Test Exam Title"},
                {"type": "text", "text": "15 Sep 2025"},
                {"type": "text", "text": "Question Paper and Answer Key"}
            ]}]
        },
        {
            "name": "recheck_request_",
            "components": [{"type": "body", "parameters": [
                {"type": "text", "text": "Test Student Name"}
            ]}]
        },
        {
            "name": "interview_reminder",
            "components": [{"type": "body", "parameters": [
                {"type": "text", "text": "Test Candidate"}
            ]}]
        },
        {
            "name": "payment_approve_reject",
            "components": [
                {
                    "type": "header",
                    "parameters": [{
                        "type": "image",
                        "image": {"link": "https://insightinstitute-fufvf3dbe0grg2b3.centralindia-01.azurewebsites.net/static/images/payment_receipt_placeholder.png"}
                    }]
                },
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": "Test Student"},
                        {"type": "text", "text": "1001"},
                        {"type": "text", "text": "CS Executive"},
                        {"type": "text", "text": "Module 1"},
                        {"type": "text", "text": "Dec 2026"},
                        {"type": "text", "text": "Full Payment"},
                        {"type": "text", "text": "Cheque"},
                        {"type": "text", "text": "40,000"},
                        {"type": "text", "text": "CHQ-123456"},
                        {"type": "text", "text": "17-Oct-2026 12:15 PM"},
                    ]
                },
                {
                    "type": "button",
                    "sub_type": "quick_reply",
                    "index": "0",
                    "parameters": [{"type": "payload", "payload": "adm_pay_approve:1001"}]
                },
                {
                    "type": "button",
                    "sub_type": "quick_reply",
                    "index": "1",
                    "parameters": [{"type": "payload", "payload": "adm_pay_reject:1001"}]
                }
            ]
        },
    ]

    print(f"Testing {len(templates_to_test)} Meta/WhatsApp templates live on number {TARGET_NUMBER}...")
    success_count = 0
    
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
                print(f"SUCCESS for {tpl['name']}! API Response: {json.dumps(response, indent=2)}")
                success_count += 1
            except Exception as e:
                print(f"ERROR for {tpl['name']}: {type(e).__name__} - {str(e)}")
                if hasattr(e, 'response') and e.response:
                    try:
                        err_data = e.response.json() if hasattr(e.response, 'json') else str(e.response.text)
                        print(f"Meta Error Details: {json.dumps(err_data, indent=2)}")
                    except:
                        print(f"Raw error response: {e.response}")
                logger.error("Template test failed", exc_info=True)
    
    print(f"\n=== TEST SUMMARY: {success_count}/{len(templates_to_test)} templates succeeded ===")
    if success_count == len(templates_to_test):
        print("All Meta templates tested successfully!")
    else:
        print("Some templates failed. Check Meta Business Manager for approval status.")
        print("Run `python get_whatsapp_templates.py` to see approved templates.")
    return success_count > 0


if __name__ == "__main__":
    test_all_meta_templates()
