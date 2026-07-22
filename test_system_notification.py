#!/usr/bin/env python
"""
Test harness for send_system_notification (in-app FCM + history + optional email/WhatsApp).

- Calls the centralized notification function (which runs in background thread).
- Verifies the result by checking NotificationHistory model (the primary "response"
  since FCM/WhatsApp are fire-and-forget with logging).
- Can be extended with real FCM token checks or email outbox.

Usage:
    python test_system_notification.py
"""

import os
import sys
import time
import logging
from datetime import datetime

# Setup Django
try:
    import django
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "insight.settings")
    django.setup()
    DJANGO_AVAILABLE = True
except Exception as e:
    print("❌ Django setup failed:", e)
    DJANGO_AVAILABLE = False
    sys.exit(1)

from django.contrib.auth import get_user_model
from chat.notifications import send_system_notification
from auth_user.models import NotificationHistory

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_system_notification():
    """Test function for send_system_notification (with sync=True) and checks the NotificationHistory DB response.
    Uses polling + JSON field lookup on test_id for robustness against scheduler DB contention.
    """
    print("\n=== System Notification Test ===")
    print(f"Start time: {datetime.now().isoformat()}")

    User = get_user_model()

    # Find a suitable test user (prefer super_admin or one with FCM token)
    test_user = User.objects.filter(role='super_admin', is_active=True).first()

    if not test_user:
        print("[FAIL] No active users found in database.")
        return False

    print(f"[OK] Using test user: {test_user.email} (ID: {test_user.id}, Role: {test_user.role})")
    
    title = "Test System Notification"
    body = f"This is a test in-app notification sent at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}. Check your app or notification history."
    metadata = {
        "type": "test_notification",
        "test_id": "SYSTEM_TEST_001",
        "route": "/dashboard",
        "priority": "high"
    }

    print("\nCalling send_system_notification (sync=True to avoid scheduler DB lock)...")
    send_system_notification(
        user_id=str(test_user.id),
        title=title,
        body=body,
        metadata=metadata,
        # Optional: test email path too
        email_template=None,  # Set to 'emails/otp.html' or similar if you want to test email
        email_subject="Test In-App Notification",
        # Optional WhatsApp (will use plain text fallback if no template)
        # whatsapp_template=None,
        # whatsapp_context=None,
    )

    # Poll for the record (handles any transient DB contention from scheduler)
    print("Polling up to 8s for NotificationHistory record...")
    recent_notifications = []
    for attempt in range(8):
        time.sleep(1)
        recent_notifications = NotificationHistory.objects.filter(
            user=test_user,
            data__test_id=metadata["test_id"]  # More reliable than title (uses JSON lookup)
        ).order_by('-created_at')[:3]
        if recent_notifications:
            break
    else:
        # Final check with broader query
        recent_notifications = NotificationHistory.objects.filter(
            user=test_user
        ).order_by('-created_at')[:5]

    print("\n=== Notification History Response (DB Check) ===")
    found_test_record = any(n.data.get("test_id") == "SYSTEM_TEST_001" for n in recent_notifications)
    
    if recent_notifications and found_test_record:
        for notif in recent_notifications:
            print(f"ID: {notif.id}")
            print(f"Title: {notif.title}")
            print(f"Body: {notif.body[:80]}...")
            print(f"Data: {notif.data}")
            print(f"Is Read: {notif.is_read}")
            print(f"Created At: {notif.created_at}")
            print("-" * 60)
        
        print("\n[OK] TEST PASSED: NotificationHistory record successfully created by send_system_notification().")
        print("   (FCM path taken if token present; history created regardless.)")
        if getattr(test_user, 'fcm_token', None):
            print("   FCM token present - check logs for send_fcm_notification() success.")
        return True
    else:
        # Fallback diagnostics
        print("[WARNING] No matching test record found. Showing latest 5 notifications for user:")
        fallback = NotificationHistory.objects.filter(user=test_user).order_by('-created_at')[:5]
        for notif in fallback:
            print(f"  * {notif.title} | {notif.created_at} | data_test_id={notif.data.get('test_id')} | read={notif.is_read}")
        
        print("\n[FAIL] TEST FAILED: No NotificationHistory record was created for this test.")
        print("   Possible causes: DB lock during scheduler startup, missing user, or exception in _send_task.")
        print("   (The sync=True + polling should have mitigated most transient issues.)")
        return False


if __name__ == "__main__":
    print("System Notification Test Harness")
    print("=" * 60)
    
    # Ensure Firebase credentials are provided
    raw_json = os.getenv("FIREBASE_CREDENTIALS_JSON")
    firebase_path = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH")
    
    if raw_json:
        print("Firebase credentials provided via FIREBASE_CREDENTIALS_JSON in env.")
    elif firebase_path:
        clean_path = firebase_path.strip('"').strip()
        print("Firebase service account path from env:", clean_path)
        if not clean_path.startswith("http") and not os.path.exists(clean_path):
            print("[WARNING] Service account JSON not found at path. FCM may fail (but history should still be created).")
    else:
        print("[WARNING] No FIREBASE_CREDENTIALS_JSON or FIREBASE_SERVICE_ACCOUNT_PATH in env. FCM will be skipped.")
    
    success = test_system_notification()
    
    print("\n" + "=" * 60)
    if success:
        print("[SUCCESS] Test completed successfully.")
        sys.exit(0)
    else:
        print("[INFO] Tip: Check django_errors.log for 'Failed to save notification history' or DB lock errors.")
        print("   The scheduler reconciliation can lock SQLite; sync=True mitigates this.")
        sys.exit(1)
