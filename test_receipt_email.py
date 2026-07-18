# -*- coding: utf-8 -*-
"""
Diagnostic test for the payment receipt email pipeline.
Run with:  python test_receipt_email.py
"""
import os, sys, io, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'insight.settings')
# Force UTF-8 on Windows console
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
django.setup()

import uuid
from decimal import Decimal
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# STEP 1: Build mock payment + student (no DB)
# ---------------------------------------------------------------------------
print("\n" + "="*60)
print("STEP 1: Building mock payment object")
print("="*60)

payment = MagicMock()
payment.id = uuid.uuid4()
payment.receipt_number = "REC-TEST-001"
payment.amount = Decimal("12500.00")
payment.payment_mode = "upi"
payment.transaction_ref = "UPI12345TEST"
payment.payment_date = None
payment.payment_document = MagicMock()
payment._receipt_generated = False

student = MagicMock()
student.id = uuid.uuid4()
student.first_name = "Test"
student.name = "Test Student"
student.full_name = "Test Student"
student.email = None
student.email_parent = None
student.user = MagicMock()
# CHANGE THIS to a real deliverable email address:
student.user.email = "harshilk.dev@gmail.com"

payment.student = student

print(f"  [OK] Payment ID  : {payment.id}")
print(f"  [OK] Receipt No  : {payment.receipt_number}")
print(f"  [OK] Amount      : Rs.{payment.amount}")
print(f"  [OK] Student user email: {student.user.email}")

# ---------------------------------------------------------------------------
# STEP 2: get_recipient_emails
# ---------------------------------------------------------------------------
print("\n" + "="*60)
print("STEP 2: Testing get_recipient_emails()")
print("="*60)
from fees.utils import get_recipient_emails
recipients = get_recipient_emails(student)
if recipients:
    print(f"  [OK] Recipients: {recipients}")
else:
    print("  [FAIL] No recipients found!")
    sys.exit("ABORT: No recipients.")

# ---------------------------------------------------------------------------
# STEP 3: Template rendering
# ---------------------------------------------------------------------------
print("\n" + "="*60)
print("STEP 3: Rendering email template")
print("="*60)
from django.template.loader import render_to_string
template_context = {
    'student_name': student.name,
    'amount': f"{payment.amount:,.2f}",
    'receipt_number': payment.receipt_number,
    'payment_mode': payment.payment_mode.title(),
    'transaction_ref': payment.transaction_ref,
    'payment_date': '',
    'primary_color': '#ed7c31',
    'org_name': 'Insight Institute of Professional Studies',
}
try:
    html = render_to_string("emails/payment_receipt.html", template_context)
    print(f"  [OK] Template rendered ({len(html)} chars)")
except Exception as e:
    print(f"  [FAIL] Template render failed: {e}")
    import traceback; traceback.print_exc()

# ---------------------------------------------------------------------------
# STEP 4: SMTP settings
# ---------------------------------------------------------------------------
print("\n" + "="*60)
print("STEP 4: Email settings")
print("="*60)
from django.conf import settings
backend = settings.EMAIL_BACKEND
print(f"  EMAIL_BACKEND  : {backend}")
print(f"  EMAIL_HOST     : {getattr(settings, 'EMAIL_HOST', '(not set)')}")
print(f"  EMAIL_PORT     : {getattr(settings, 'EMAIL_PORT', '(not set)')}")
print(f"  EMAIL_HOST_USER: {getattr(settings, 'EMAIL_HOST_USER', '(not set)')}")
print(f"  EMAIL_USE_TLS  : {getattr(settings, 'EMAIL_USE_TLS', '(not set)')}")
print(f"  DEFAULT_FROM   : {getattr(settings, 'DEFAULT_FROM_EMAIL', '(not set)')}")
if any(x in backend for x in ('console', 'locmem', 'dummy', 'filebased')):
    print(f"\n  [WARNING] Non-sending backend. Emails will NOT be delivered.")
else:
    print(f"  [OK] SMTP backend active.")

# ---------------------------------------------------------------------------
# STEP 5: Direct send_email test
# ---------------------------------------------------------------------------
print("\n" + "="*60)
print("STEP 5: Calling send_email() directly")
print("="*60)
from core.sender import send_email
try:
    result = send_email(
        to=recipients,
        subject=f"[TEST] Payment Receipt - {payment.receipt_number}",
        text=f"[TEST] Receipt {payment.receipt_number} Rs.{payment.amount}",
        template="emails/payment_receipt.html",
        template_context=template_context,
        attachments=[],
    )
    print(f"  [OK] send_email returned: {result} -> email sent to {recipients}")
except Exception as e:
    print(f"  [FAIL] send_email raised: {e}")
    import traceback; traceback.print_exc()

# ---------------------------------------------------------------------------
# STEP 6: Full send_payment_receipt()
# ---------------------------------------------------------------------------
print("\n" + "="*60)
print("STEP 6: Calling send_payment_receipt() end-to-end")
print("="*60)
payment._receipt_generated = False
from fees.services import send_payment_receipt
try:
    send_payment_receipt(payment)
    print("  [OK] send_payment_receipt() finished without exception")
except Exception as e:
    print(f"  [FAIL] send_payment_receipt() raised: {e}")
    import traceback; traceback.print_exc()

print("\n" + "="*60)
print("DONE - review any [FAIL] or [WARNING] lines above")
print("="*60 + "\n")
