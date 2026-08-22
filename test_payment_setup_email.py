# -*- coding: utf-8 -*-
"""
Diagnostic test for the admission payment setup email (HTML template + plain text).
Tests the new payment_setup.html template used by _setup_payment_bank_and_notify().
Run with:  python test_payment_setup_email.py
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
# STEP 1: Build mock admission + bank
# ---------------------------------------------------------------------------
print("\n" + "="*70)
print("STEP 1: Building mock admission + bank object")
print("="*70)

admission = MagicMock()
admission.id = uuid.uuid4()
admission.first_name = "Test"
admission.surname = "Student"
admission.email = "harshilk.dev@gmail.com"
admission.phone_student = "9876543210"
admission.status = "payment_pending"
admission.razorpay_payment_link = "https://rzp.io/i/TESTPAYLINK123"
admission.branch = MagicMock()
admission.branch.organization = None

bank = MagicMock()
bank.bank_name = "HDFC Bank"
bank.name = "Insight Institute Pvt. Ltd."
bank.account_number = "50200045678901"
bank.ifsc_code = "HDFC0000567"
bank.branch_name = "CG Road, Ahmedabad"

print(f"  [OK] Admission ID : {admission.id}")
print(f"  [OK] Student      : {admission.first_name} {admission.surname}")
print(f"  [OK] Email        : {admission.email}")
print(f"  [OK] Razorpay Link: {admission.razorpay_payment_link}")
print(f"  [OK] Bank         : {bank.bank_name} ({bank.account_number})")

# ---------------------------------------------------------------------------
# STEP 2: Template rendering test
# ---------------------------------------------------------------------------
print("\n" + "="*70)
print("STEP 2: Rendering payment_setup.html template")
print("="*70)
from django.template.loader import render_to_string

template_context = {
    'student_name': f"{admission.first_name} {admission.surname}",
    'razorpay_link': admission.razorpay_payment_link,
    'amount': '12500',
    'bank_name': bank.bank_name,
    'account_holder': bank.name,
    'account_number': bank.account_number,
    'ifsc_code': bank.ifsc_code,
    'branch': bank.branch_name,
    'upload_link': f"https://example.com/insight/student/payment-upload?id={admission.id}",
    'primary_color': '#ed7c31',
    'org_name': 'Insight Institute of Professional Studies',
}

try:
    html = render_to_string("emails/payment_setup.html", template_context)
    print(f"  [OK] Template rendered successfully ({len(html)} chars)")
    print("  [OK] Contains Razorpay button: " + ("✅ YES" if 'Pay ₹12500 Now' in html else "❌ NO"))
    print("  [OK] Contains upload button: " + ("✅ YES" if 'Upload Screenshot' in html else "❌ NO"))
except Exception as e:
    print(f"  [FAIL] Template render failed: {e}")
    import traceback; traceback.print_exc()
    sys.exit(1)

# ---------------------------------------------------------------------------
# STEP 3: Plain text version (as original)
# ---------------------------------------------------------------------------
print("\n" + "="*70)
print("STEP 3: Plain text content (as it was originally)")
print("="*70)
payment_link = template_context['upload_link']
razorpay_link_url = template_context['razorpay_link']
bank_details = (
    f"Bank Name       : {bank.bank_name}\n"
    f"Account Holder  : {bank.name}\n"
    f"Account Number  : {bank.account_number}\n"
    f"IFSC Code       : {bank.ifsc_code}\n"
    f"Branch          : {bank.branch_name}\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
)
text_content = (
    f"Hello {admission.first_name},\n\n"
    f"Thank you for submitting your admission form. "
    f"Please complete your fee payment to proceed with your enrollment.\n\n"
    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    f"ONLINE PAYMENT LINK\n"
    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    f"You can instantly pay online using the secure Razorpay link below:\n"
    f"{razorpay_link_url}\n\n"
    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    f"OFFLINE BANK DETAILS FOR FEE PAYMENT\n"
    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    f"{bank_details}"
    f"If you paid via offline bank transfer, please click the link below to "
    f"upload your payment screenshot and transaction ID:\n\n"
    f"{payment_link}\n\n"
    f"If you have any questions, feel free to reach out to your counsellor.\n\n"
    f"Best Regards,\n"
    f"Insight Institute Team"
)

print("Plain text preview (first 400 chars):")
print("-" * 50)
print(text_content[:400] + "...")
print("-" * 50)
print(f"  [OK] Text length: {len(text_content)} chars")
print(f"  [OK] Contains Razorpay link: {'✅ YES' if razorpay_link_url in text_content else '❌ NO'}")

# ---------------------------------------------------------------------------
# STEP 4: SMTP / sender test
# ---------------------------------------------------------------------------
print("\n" + "="*70)
print("STEP 4: Email settings + send_email() test")
print("="*70)
from django.conf import settings
from core.sender import send_email

print(f"  EMAIL_BACKEND  : {settings.EMAIL_BACKEND}")
print(f"  EMAIL_HOST     : {getattr(settings, 'EMAIL_HOST', '(not set)')}")
print(f"  DEFAULT_FROM   : {getattr(settings, 'DEFAULT_FROM_EMAIL', '(not set)')}")

recipients = [admission.email]
subject = "Test: Complete Your Fee Payment - Razorpay Link Inside"

try:
    result = send_email(
        to=recipients,
        subject=subject,
        text=text_content,
        template="emails/payment_setup.html",
        template_context=template_context,
    )
    print(f"  [OK] send_email() returned: {result}")
    print(f"  [OK] Email sent to: {recipients} (HTML + rich plaintext)")
except Exception as e:
    print(f"  [FAIL] send_email failed: {e}")
    import traceback; traceback.print_exc()

# ---------------------------------------------------------------------------
# STEP 5: Full function test (mocked)
# ---------------------------------------------------------------------------
print("\n" + "="*70)
print("STEP 5: Mock _setup_payment_bank_and_notify()")
print("="*70)
def mock_setup(admission_mock, bank_mock):
    """Mock version of the function to test email path."""
    from core.sender import send_email
    print("  [MOCK] Bank assigned, status history created, Razorpay link generated")
    payment_link_url = f"https://example.com/insight/student/payment-upload?id={admission_mock.id}"
    # Use the same context as production
    ctx = {
        'student_name': f"{admission_mock.first_name} {admission_mock.surname}",
        'razorpay_link': admission_mock.razorpay_payment_link,
        'amount': '12500',
        'bank_name': bank_mock.bank_name,
        'account_holder': bank_mock.name,
        'account_number': bank_mock.account_number,
        'ifsc_code': bank_mock.ifsc_code,
        'branch': bank_mock.branch_name,
        'upload_link': payment_link_url,
        'primary_color': '#ed7c31',
        'org_name': 'Insight Institute of Professional Studies',
    }
    # In real call it would use the rich text_content too
    send_email(
        to=admission_mock.email,
        subject="Test Payment Setup Email",
        text="Test plaintext fallback",
        template="emails/payment_setup.html",
        template_context=ctx,
    )
    print("  [OK] Mock function executed — email with HTML template dispatched")

mock_setup(admission, bank)

print("\n" + "="*70)
print("✅ TEST COMPLETE — review output above for any issues.")
print("The Razorpay link should now appear as a prominent button in HTML emails.")
print("Plain text version preserved exactly as original.")
print("="*70)
