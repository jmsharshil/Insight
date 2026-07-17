#!/usr/bin/env python
import os
import django
import logging
from datetime import datetime

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'insight.settings')
django.setup()

from core.sender import WhatsAppConfig, WhatsAppSender
from django.conf import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_whatsapp():
    phone_id = "479507930369273"
    access_token = "EAAWgu2e9C2ABR1YqwHBFGksKiQPJSfMWg53ezZCIahO1jpu9hCwC22RZBE29xF51gZBcY774iVVsZA8WFXfZA812HXdtn7KiN0vzpgCjICZAmWhW441H9OFbsFQFoIY4hDgJHFZBoufO1bWVI8VzlforzY9dWCfwxNr4ZBtcup81Jk2yqsAefmArSVNBXohGN0eu1gZDZD"
    
    print("=== WhatsApp Credentials Test ===")
    print("Phone ID:", phone_id)
    print("Token prefix:", access_token[:20] + "...")
    print("Target number: +91 8401611072 (formatted as 918401611072)")
    
    config = WhatsAppConfig(
        phone_number_id=phone_id,
        access_token=access_token,
    )
    print("Config initialized successfully.")
    
    to_number = "1111111111"
    message = f"Test WhatsApp message from Insight ERP at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}. This is a test."
    print("Message prepared:", message[:60] + "...")
    
    try:
        print("Initializing WhatsAppSender...")
        with WhatsAppSender(config) as wa:
            print("Sender initialized, sending text message...")
            response = wa.send_text(to=to_number, body=message)
            print("SUCCESS! API Response:", response)
            print("Message sent successfully to", to_number)
            return True
    except Exception as e:
        print("ERROR:", type(e).__name__, "-", str(e))
        if hasattr(e, 'error_code'):
            print("Meta Error Code:", getattr(e, 'error_code', None))
        if hasattr(e, 'status_code'):
            print("HTTP Status:", getattr(e, 'status_code', None))
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    test_whatsapp()
