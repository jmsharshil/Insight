"""
test_button_templates.py
========================
Tests WhatsApp templates that contain button components.

Templates tested:
  1. payment_approve_reject  — quick_reply buttons (Approve / Reject)
                               + IMAGE header + 10 body params
                               + CRM log should include fallback_body & wamid
  2. admission_process       — URL button (dynamic suffix)
  3. WHATSAPP_STUDENT_LEAVE_TEMPLATE (if configured) — quick_reply buttons

Run from project root:
    python test_button_templates.py
"""

import os, sys, json, logging

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "insight.settings")

try:
    import django
    django.setup()
except Exception as e:
    print(f"Django setup failed: {e}")
    sys.exit(1)

from django.conf import settings
import pytz, requests as _req
from django.utils import timezone

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
TARGET_NUMBER  = "918401611072"          # test recipient
PHONE_ID       = getattr(settings, "WHATSAPP_PHONE_NUMBER_ID", "")
ACCESS_TOKEN   = getattr(settings, "WHATSAPP_ACCESS_TOKEN", "")
CRM_WEBHOOK    = "https://whatsappcrmsaas-emdke9dnb4f8bne6.centralindia-01.azurewebsites.net/webhook/"

IST = pytz.timezone("Asia/Kolkata")

# ── Helpers ───────────────────────────────────────────────────────────────────

def now_ist_str():
    return timezone.now().astimezone(IST).strftime("%Y-%m-%d %H:%M:%S IST")

def send_direct(template_name, components, language_code="en"):
    """Send via WhatsAppSender directly (bypasses task queue) and return raw result."""
    from core.whatsapp import WhatsAppConfig, WhatsAppSender
    config = WhatsAppConfig(
        phone_number_id=PHONE_ID,
        access_token=ACCESS_TOKEN,
    )
    with WhatsAppSender(config) as wa:
        return wa.send_template(
            to=TARGET_NUMBER,
            template_name=template_name,
            language_code=language_code,
            components=components,
        )

def check_crm_log(phone, content, message_id, template_name):
    """Fire the CRM log payload and print what was sent."""
    payload = {
        "is_insight_log": True,
        "phone": phone,
        "content": content,
        "bot_name": "Insights",
        "phone_number_id": "1168578376348442",
        "timestamp": now_ist_str(),
    }
    if message_id:
        payload["message_id"] = message_id

    print(f"\n  [CRM LOG] Payload for {template_name}:")
    print(f"    phone      = {payload['phone']}")
    print(f"    timestamp  = {payload['timestamp']}")
    print(f"    message_id = {payload.get('message_id', '(missing — wamid not extracted)')}")
    print(f"    content    = {payload['content'][:120]}...")

    try:
        resp = _req.post(CRM_WEBHOOK, json=payload, timeout=6)
        print(f"    CRM HTTP   = {resp.status_code}")
    except Exception as e:
        print(f"    CRM ERROR  = {e}")

def run_test(label, template_name, components, fallback_body, language_code="en"):
    print(f"\n{'='*60}")
    print(f"TEST: {label}")
    print(f"  template  : {template_name}")
    print(f"  to        : {TARGET_NUMBER}")
    print(f"  buttons   : {[c for c in components if c.get('type') == 'button']}")

    try:
        result = send_direct(template_name, components, language_code)
        wamid = None
        if isinstance(result, dict):
            msgs = result.get("messages", [])
            if msgs:
                wamid = msgs[0].get("id")
        print(f"  STATUS    : ✅ SENT")
        print(f"  Meta resp : {json.dumps(result)}")
        print(f"  wamid     : {wamid}")
        check_crm_log(TARGET_NUMBER, fallback_body, wamid, template_name)
    except Exception as exc:
        print(f"  STATUS    : ❌ ERROR — {type(exc).__name__}: {exc}")
        if hasattr(exc, "error_code"):
            print(f"  Meta code : {exc.error_code}")

# ── Test 1: payment_approve_reject (quick_reply buttons + image header) ───────
PLACEHOLDER_IMG = (
    "https://insightinstitute-fufvf3dbe0grg2b3.centralindia-01.azurewebsites.net"
    "/static/images/payment_receipt_placeholder.png"
)

payment_approve_reject_components = [
    {
        "type": "header",
        "parameters": [{"type": "image", "image": {"link": PLACEHOLDER_IMG}}]
    },
    {
        "type": "body",
        "parameters": [
            {"type": "text", "text": "Test Student"},       # {{1}} Student Name
            {"type": "text", "text": "9999"},               # {{2}} Admission ID
            {"type": "text", "text": "CA Foundation"},      # {{3}} Course Type
            {"type": "text", "text": "Group 1"},            # {{4}} Module
            {"type": "text", "text": "May 2026"},           # {{5}} Attempt
            {"type": "text", "text": "Full Payment"},       # {{6}} Payment Type
            {"type": "text", "text": "Online"},             # {{7}} Payment Mode
            {"type": "text", "text": "10,000"},             # {{8}} Amount
            {"type": "text", "text": "TXN-TEST-001"},       # {{9}} Transaction ID
            {"type": "text", "text": now_ist_str()},        # {{10}} Submitted At (IST)
        ]
    },
    {
        "type": "button",
        "sub_type": "quick_reply",
        "index": "0",
        "parameters": [{"type": "payload", "payload": "adm_pay_approve:9999"}]
    },
    {
        "type": "button",
        "sub_type": "quick_reply",
        "index": "1",
        "parameters": [{"type": "payload", "payload": "adm_pay_reject:9999"}]
    },
]

payment_fallback = (
    "FEE PAYMENT VERIFICATION\n\n"
    "Student: Test Student | Admission: 9999 | Course: CA Foundation\n"
    "Amount: Rs.10,000 | Mode: Online | TXN: TXN-TEST-001\n"
    "Submitted At: " + now_ist_str() + "\n\n"
    "Reply APPROVE 9999 or REJECT 9999"
)

run_test(
    label="payment_approve_reject (image header + 10 body params + 2 quick_reply buttons)",
    template_name="payment_approve_reject",
    components=payment_approve_reject_components,
    fallback_body=payment_fallback,
)

# ── Test 2: admission_process (URL button) ────────────────────────────────────
admission_process_components = [
    {
        "type": "body",
        "parameters": [
            {"type": "text", "text": "Test Student"},
            {"type": "text", "text": "Insight Institute of Professional Studies"},
        ],
    },
    {
        "type": "button",
        "sub_type": "url",
        "index": "0",
        "parameters": [{"type": "text", "text": "insight/student/admission-form?id=9999"}],
    },
]
admission_fallback = (
    "Dear Test Student,\n\n"
    "Your admission form is ready at Insight Institute of Professional Studies.\n"
    "Complete your admission form: https://insightinstitute.co/insight/student/admission-form?id=9999\n\n"
    "Regards, Insight ERP"
)

run_test(
    label="admission_process (body params + URL button)",
    template_name="admission_process",
    components=admission_process_components,
    fallback_body=admission_fallback,
)

# ── Test 3: student leave template (if configured) ────────────────────────────
student_leave_template = getattr(settings, "WHATSAPP_STUDENT_LEAVE_TEMPLATE", None)
if student_leave_template:
    leave_components = [
        {
            "type": "body",
            "parameters": [
                {"type": "text", "text": "Test Student"},   # student_name
                {"type": "text", "text": "Sick Leave"},     # leave_type
                {"type": "text", "text": "2026-11-01"},     # from_date
                {"type": "text", "text": "2026-11-02"},     # to_date
                {"type": "text", "text": "Fever"},          # reason
            ]
        },
        {
            "type": "button",
            "sub_type": "quick_reply",
            "index": "0",
            "parameters": [{"type": "payload", "payload": "approve_student_leave_1"}]
        },
        {
            "type": "button",
            "sub_type": "quick_reply",
            "index": "1",
            "parameters": [{"type": "payload", "payload": "reject_student_leave_1"}]
        },
    ]
    leave_fallback = (
        "LEAVE REQUEST: Test Student applied for Sick Leave\n"
        "From: 2026-11-01 To: 2026-11-02\nReason: Fever\n"
        "Reply APPROVE or REJECT."
    )
    run_test(
        label=f"Student leave template: {student_leave_template} (quick_reply buttons)",
        template_name=student_leave_template,
        components=leave_components,
        fallback_body=leave_fallback,
    )
else:
    print("\n[SKIP] WHATSAPP_STUDENT_LEAVE_TEMPLATE not set in settings — skipping leave button test")

print(f"\n{'='*60}")
print("All button template tests complete.")

