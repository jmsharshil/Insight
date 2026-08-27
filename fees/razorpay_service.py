"""
fees/razorpay_service.py
────────────────────────
Reusable Razorpay helper functions. Import from here wherever you need
Razorpay functionality — views, tasks, signals, management commands, etc.

All functions return a plain dict:
    { "success": True/False, "data": ..., "error": "..." }
so callers can decide how to surface errors (HTTP response, log, retry, etc.).
"""
import hmac
import hashlib
import json
import logging

import requests as http_requests
from requests.auth import HTTPBasicAuth
from django.conf import settings

logger = logging.getLogger(__name__)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _auth() -> HTTPBasicAuth:
    return HTTPBasicAuth(
        getattr(settings, 'RAZORPAY_KEY_ID', ''),
        getattr(settings, 'RAZORPAY_KEY_SECRET', ''),
    )


def is_razorpay_enabled() -> bool:
    """Return True if Razorpay credentials are configured in settings."""
    return bool(getattr(settings, 'RAZORPAY_KEY_ID', ''))


def _to_paise(amount_inr) -> int:
    """Convert an INR amount (int/float/Decimal) to paise (integer)."""
    return int(float(amount_inr) * 100)


# ── Payment Link ──────────────────────────────────────────────────────────────

def create_payment_link(
    *,
    amount,
    reference_id,
    customer_name,
    customer_email,
    customer_contact,
    description="Fee Payment",
    bank_account_data=None,
    upi_id=None,
) -> dict:
    """
    Create a Razorpay Payment Link.

    Args:
        amount              – Amount in INR (int/float/Decimal).
        reference_id        – Unique reference string (e.g. "ADM_42", "SF_<uuid>_token_full").
        customer_name       – Student / payer full name.
        customer_email      – Customer email.
        customer_contact    – Customer phone (10-digit, no country code prefix needed).
        description         – Short description shown on the payment page.
        bank_account_data   – Dictionary with {'account_number': ..., 'name': ..., 'ifsc': ...} 
                              for direct Netbanking/UPI routing via options.order.bank_account.
        upi_id              – (Unused in API; UPI deep-link is built separately.)

    Returns:
        { "success": True, "data": <razorpay response dict> }
        or
        { "success": False, "error": "<message>", "detail": <raw response> }
    """
    if not is_razorpay_enabled():
        return {"success": False, "error": "Razorpay is not configured on this server."}

    try:
        if float(amount) <= 0:
            return {"success": False, "error": "Amount must be greater than zero to create a payment link."}
    except (ValueError, TypeError):
        return {"success": False, "error": "Invalid amount provided."}

    payload = {
        "amount": _to_paise(amount),
        "currency": "INR",
        "accept_partial": False,
        "reference_id": str(reference_id),
        "description": description,
        "customer": {
            "name": customer_name or "",
            "email": customer_email or "",
            "contact": str(customer_contact or ""),
        },
        "notify": {
            "sms": True,
            "email": True
        },
        "reminder_enable": True,
    }

    if bank_account_data and isinstance(bank_account_data, dict):
        payload["options"] = {
            "order": {
                "bank_account": {
                    "account_number": bank_account_data.get("account_number", ""),
                    "name": bank_account_data.get("name", ""),
                    "ifsc": bank_account_data.get("ifsc", "")
                }
            }
        }

    try:
        resp = http_requests.post(
            "https://api.razorpay.com/v1/payment_links",
            json=payload,
            auth=_auth(),
            timeout=15,
        )
        if resp.status_code in (200, 201):
            return {"success": True, "data": resp.json()}
        logger.error(f"Razorpay create_payment_link error [{resp.status_code}]: {resp.text}")
        return {"success": False, "error": "Razorpay rejected the request.", "detail": resp.json()}
    except Exception as exc:
        logger.error(f"Razorpay create_payment_link exception: {exc}")
        return {"success": False, "error": str(exc)}


def build_upi_link(*, upi_id, amount, payee_name="Insight Institute", note="Fee Payment") -> str:
    """
    Build a UPI deep-link (works on mobile; opens GPay / PhonePe / Paytm).

    Returns a raw URI string, e.g.
        upi://pay?pa=abc@okaxis&pn=Insight%20Institute&am=5000&cu=INR&tn=Fee%20Payment
    Returns "" if upi_id is empty.
    """
    if not upi_id:
        return ""
    from urllib.parse import quote
    return (
        f"upi://pay?pa={quote(upi_id)}"
        f"&pn={quote(payee_name)}"
        f"&am={float(amount)}"
        f"&cu=INR"
        f"&tn={quote(note)}"
    )


def fetch_payment_link(link_id: str) -> dict:
    """
    Fetch live status of a Razorpay payment link.

    Returns:
        { "success": True, "data": { id, reference_id, short_url, amount, amount_paid, status, payments } }
    """
    if not is_razorpay_enabled():
        return {"success": False, "error": "Razorpay is not configured."}
    try:
        resp = http_requests.get(
            f"https://api.razorpay.com/v1/payment_links/{link_id}",
            auth=_auth(),
            timeout=15,
        )
        if resp.status_code == 200:
            rp = resp.json()
            return {
                "success": True,
                "data": {
                    "id": rp.get("id"),
                    "reference_id": rp.get("reference_id"),
                    "short_url": rp.get("short_url"),
                    "amount": rp.get("amount", 0) / 100,
                    "amount_paid": rp.get("amount_paid", 0) / 100,
                    "status": rp.get("status"),
                    "payments": rp.get("payments", []),
                },
            }
        logger.error(f"Razorpay fetch_payment_link [{resp.status_code}]: {resp.text}")
        return {"success": False, "error": "Payment link not found.", "detail": resp.json()}
    except Exception as exc:
        logger.error(f"Razorpay fetch_payment_link exception: {exc}")
        return {"success": False, "error": str(exc)}


def cancel_payment_link(link_id: str) -> dict:
    """
    Cancel / expire a Razorpay payment link so it can no longer be paid.

    Returns:
        { "success": True, "data": <razorpay response> }
    """
    if not is_razorpay_enabled():
        return {"success": False, "error": "Razorpay is not configured."}
    try:
        resp = http_requests.post(
            f"https://api.razorpay.com/v1/payment_links/{link_id}/cancel",
            auth=_auth(),
            timeout=15,
        )
        if resp.status_code == 200:
            return {"success": True, "data": resp.json()}
        logger.error(f"Razorpay cancel_payment_link [{resp.status_code}]: {resp.text}")
        return {"success": False, "error": "Failed to cancel payment link.", "detail": resp.json()}
    except Exception as exc:
        logger.error(f"Razorpay cancel_payment_link exception: {exc}")
        return {"success": False, "error": str(exc)}


# ── Payments ──────────────────────────────────────────────────────────────────

def fetch_payment(razorpay_payment_id: str) -> dict:
    """
    Fetch full details of a specific Razorpay payment.

    Returns:
        { "success": True, "data": <razorpay payment object> }
    """
    if not is_razorpay_enabled():
        return {"success": False, "error": "Razorpay is not configured."}
    try:
        resp = http_requests.get(
            f"https://api.razorpay.com/v1/payments/{razorpay_payment_id}",
            auth=_auth(),
            timeout=15,
        )
        if resp.status_code == 200:
            return {"success": True, "data": resp.json()}
        logger.error(f"Razorpay fetch_payment [{resp.status_code}]: {resp.text}")
        return {"success": False, "error": "Payment not found.", "detail": resp.json()}
    except Exception as exc:
        logger.error(f"Razorpay fetch_payment exception: {exc}")
        return {"success": False, "error": str(exc)}


# ── Refunds ───────────────────────────────────────────────────────────────────

def create_refund(*, payment_id: str, amount, reason: str = "") -> dict:
    """
    Trigger a refund for a Razorpay payment.

    Args:
        payment_id  – Razorpay payment ID (e.g. "pay_xxx").
        amount      – Amount to refund in INR.
        reason      – Human-readable reason string (stored in notes).

    Returns:
        { "success": True, "data": <razorpay refund object> }
    """
    if not is_razorpay_enabled():
        return {"success": False, "error": "Razorpay is not configured."}
    try:
        resp = http_requests.post(
            f"https://api.razorpay.com/v1/payments/{payment_id}/refund",
            json={
                "amount": _to_paise(amount),
                "notes": {"reason": reason},
            },
            auth=_auth(),
            timeout=15,
        )
        if resp.status_code in (200, 201):
            return {"success": True, "data": resp.json()}
        logger.error(f"Razorpay create_refund [{resp.status_code}]: {resp.text}")
        return {"success": False, "error": "Razorpay refund failed.", "detail": resp.json()}
    except Exception as exc:
        logger.error(f"Razorpay create_refund exception: {exc}")
        return {"success": False, "error": str(exc)}


# ── Webhook ───────────────────────────────────────────────────────────────────

def verify_webhook_signature(body: bytes, signature: str) -> bool:
    """
    Verify a Razorpay webhook signature using HMAC-SHA256.

    Args:
        body       – Raw request body bytes.
        signature  – Value of the X-Razorpay-Signature header.

    Returns True if the signature matches, False otherwise.
    If RAZORPAY_WEBHOOK_SECRET is not set, returns True (no verification).
    """
    secret = getattr(settings, 'RAZORPAY_WEBHOOK_SECRET', '')
    if not secret:
        return True  # No secret configured — skip verification (not recommended in prod)
    expected = hmac.new(
        secret.encode('utf-8'),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def send_admission_payment_notification(admission, amount_paid: float, rp_payment_id: str):
    """
    Send payment confirmation email + WhatsApp to the student (and parent if available)
    when a Razorpay payment_link.paid event is received for an Admission (ADM_ flow).
    This is called before the student is fully enrolled — no Payment model object exists yet.
    Generates an auto-PDF receipt using _reportlab_receipt_pdf and attaches it to both
    the email and the WhatsApp document message.
    """
    try:
        from core.sender import send_email
        from io import BytesIO
        from django.utils import timezone as tz
        from .pdf_services import _reportlab_receipt_pdf

        student_name = f"{getattr(admission, 'first_name', '')} {getattr(admission, 'surname', '')}".strip()
        receipt_number = f"ADM-RZP-{rp_payment_id[:10]}" if rp_payment_id else f"ADM-{admission.id}"
        receipt_date = tz.localtime().strftime('%d %b, %Y')

        subject = f"Payment Receipt – ₹{amount_paid:,.0f} | Insight Institute"
        text_body = (
            f"Dear {student_name},\n\n"
            f"We have received your payment of ₹{amount_paid:,.2f} via Razorpay.\n\n"
            f"Receipt No     : {receipt_number}\n"
            f"Transaction ID : {rp_payment_id or 'N/A'}\n"
            f"Amount         : ₹{amount_paid:,.2f}\n"
            f"Date           : {receipt_date}\n"
            f"Status         : Payment Received — Pending Enrollment Approval\n\n"
            f"Your official receipt is attached to this email. "
            f"Our team will complete your enrollment shortly. "
            f"You will receive your login credentials once approved.\n\n"
            f"Thank you,\nInsight Institute of Professional Studies"
        )
        template_context = {
            'student_name': student_name,
            'amount': f"{float(amount_paid):,.2f}",
            'receipt_number': receipt_number,
            'payment_mode': 'Razorpay (Online)',
            'transaction_ref': rp_payment_id or 'N/A',
            'payment_date': receipt_date,
            'primary_color': '#ed7c31',
            'org_name': 'Insight Institute of Professional Studies',
        }

        # ── Generate PDF receipt using reportlab (pure Python, no WeasyPrint needed) ──
        pdf_attachment = None
        pdf_bytes = None
        try:
            from core.number_utils import num2words
            reportlab_context = {
                'receipt_no': receipt_number,
                'receipt_date': receipt_date,
                'student_name': student_name,
                'amount': f"₹{float(amount_paid):,.2f}",
                'amount_words': num2words(amount_paid),
                'batch_name': 'N/A',
                'payment_type': 'token',
                'payment_mode': 'online',
                'transaction_ref': rp_payment_id or 'N/A',
                'transaction_date': receipt_date,
            }
            pdf_buffer = _reportlab_receipt_pdf(reportlab_context)
            if pdf_buffer and pdf_buffer.getvalue():
                pdf_bytes = pdf_buffer.getvalue()
                pdf_filename = f"Receipt_{receipt_number}.pdf"
                pdf_attachment = (pdf_filename, pdf_bytes, 'application/pdf')
                logger.info(f"[Razorpay] ADM receipt PDF generated ({len(pdf_bytes)} bytes)")
            else:
                logger.warning(f"[Razorpay] ADM receipt PDF empty for admission {admission.id}")
        except Exception as pdf_err:
            logger.error(f"[Razorpay] ADM receipt PDF generation failed: {pdf_err}", exc_info=True)

        # ── Build recipient email list ──────────────────────────────────────────────
        recipients = set()
        if getattr(admission, 'email', None):
            recipients.add(admission.email)
        if getattr(admission, 'email_parent', None):
            recipients.add(admission.email_parent)
        recipients = list(filter(None, recipients))

        attachments = [pdf_attachment] if pdf_attachment else []
        for recipient in recipients:
            try:
                send_email(
                    to=recipient,
                    subject=subject,
                    text=text_body,
                    template="emails/payment_receipt.html",
                    template_context=template_context,
                    attachments=attachments,
                    organization=admission.branch.organization if getattr(admission, 'branch', None) else None,
                )
                logger.info(
                    f"[Razorpay] ADM payment receipt email sent to {recipient}"
                    + (" (with PDF)" if pdf_attachment else " (no PDF)")
                )
            except Exception as mail_err:
                logger.error(f"[Razorpay] ADM payment email failed to {recipient}: {mail_err}")

        # ── WhatsApp notification with PDF document ─────────────────────────────────
        try:
            from chat.notifications import send_whatsapp_with_fallback, send_whatsapp_media

            phones = []
            if getattr(admission, 'phone_student', None):
                phones.append(admission.phone_student)
            if getattr(admission, 'phone_father', None):
                phones.append(admission.phone_father)
            phones = list(set(filter(None, phones)))

            if not phones:
                logger.info(f"[Razorpay] No WhatsApp phones for ADM {admission.id} — skipping WA.")
            else:
                wa_caption = (
                    f"✅ *Payment Receipt — Insight Institute*\n"
                    f"Dear {student_name},\n\n"
                    f"Your payment of ₹{amount_paid:,.0f} has been received via Razorpay.\n"
                    f"Receipt No    : {receipt_number}\n"
                    f"Transaction ID: {rp_payment_id or 'N/A'}\n"
                    f"Date          : {receipt_date}\n\n"
                    f"Your enrollment is pending approval. "
                    f"You will receive login credentials once approved.\n"
                    f"— Insight Institute of Professional Studies"
                )

                # Upload PDF to Azure Blob and share as WhatsApp document
                pdf_public_url = None
                if pdf_bytes:
                    try:
                        from django.core.files.base import ContentFile
                        from django.core.files.storage import default_storage
                        blob_path = f"receipts/admissions/{receipt_number}.pdf"
                        blob_name = default_storage.save(blob_path, ContentFile(pdf_bytes))
                        pdf_public_url = default_storage.url(blob_name)
                        logger.info(f"[Razorpay] ADM receipt PDF uploaded to: {pdf_public_url}")
                    except Exception as upload_err:
                        logger.error(f"[Razorpay] ADM PDF upload for WhatsApp failed: {upload_err}")

                for phone in phones:
                    try:
                        if pdf_public_url:
                            send_whatsapp_media(
                                to=phone,
                                media_type='document',
                                link=pdf_public_url,
                                caption=wa_caption,
                                filename=f"Receipt_{receipt_number}.pdf",
                            )
                            logger.info(f"[Razorpay] ADM WhatsApp receipt (PDF) sent to {phone}")
                        else:
                            send_whatsapp_with_fallback(
                                to=phone,
                                template_name="admission_process",
                                language_code="en",
                                components=[{"type": "body", "parameters": [{"type": "text", "text": student_name}]}],
                                fallback_body=wa_caption,
                            )
                            logger.info(f"[Razorpay] ADM WhatsApp receipt (template/text) sent to {phone}")
                    except Exception as wa_err:
                        logger.error(f"[Razorpay] ADM WhatsApp failed to {phone}: {wa_err}")
        except Exception as wa_import_err:
            logger.error(f"[Razorpay] WhatsApp import failed: {wa_import_err}")

    except Exception as exc:
        logger.error(f"[Razorpay] send_admission_payment_notification error: {exc}", exc_info=True)


def process_payment_link_paid_event(payload: dict) -> dict:
    """
    Handle the 'payment_link.paid' Razorpay webhook event.

    Supports two reference_id conventions:
        - "SF_<student_fee_uuid>_<payment_type>"  → updates StudentFee + sends receipt
        - "ADM_<admission_id>"                    → updates Admission + sends confirmation

    Returns:
        { "success": True, "processed": "SF"|"ADM"|"unknown" }
    """
    from django.utils import timezone

    try:
        link_entity   = payload.get('payload', {}).get('payment_link', {}).get('entity', {})
        pay_entity    = payload.get('payload', {}).get('payment', {}).get('entity', {})
        reference_id  = link_entity.get('reference_id', '')
        amount_paid   = link_entity.get('amount_paid', 0) / 100
        rp_payment_id = pay_entity.get('id', '') or link_entity.get('id', '')

        # ── StudentFee flow ───────────────────────────────────────────────
        if reference_id.startswith('SF_'):
            parts = reference_id.split('_')
            sf_id = parts[1] if len(parts) > 1 else None
            if not sf_id:
                return {"success": False, "error": "Could not parse SF id from reference_id."}

            from .models import StudentFee, Payment
            from .utils import update_student_fee_status

            try:
                sf = StudentFee.objects.select_related('student').get(pk=sf_id)
            except StudentFee.DoesNotExist:
                logger.error(f"Razorpay webhook: StudentFee {sf_id} not found.")
                return {"success": False, "error": f"StudentFee {sf_id} not found."}

            payment = Payment.objects.create(
                student         = sf.student,
                student_fee     = sf,
                amount          = amount_paid,
                payment_mode    = 'online',
                transaction_ref = rp_payment_id,
                status          = 'verified',
                payment_date    = timezone.now().date(),
                note            = f"Auto-verified via Razorpay webhook. Link: {link_entity.get('id')}",
            )
            update_student_fee_status(sf.id)
            logger.info(f"[Razorpay] StudentFee {sf_id} verified. Payment: {payment.id}")

            # ── Auto-send receipt (email + WhatsApp) ─────────────────────
            try:
                from .services import send_payment_receipt
                send_payment_receipt(payment)
                logger.info(f"[Razorpay] Receipt sent for Payment {payment.id}")
            except Exception as receipt_err:
                logger.error(f"[Razorpay] Failed to send receipt for Payment {payment.id}: {receipt_err}")

            return {"success": True, "processed": "SF", "payment_id": str(payment.id)}

        # ── Admission flow ────────────────────────────────────────────────
        elif reference_id.startswith('ADM_'):
            adm_id = reference_id.split('_')[1]

            from onboarding.models import Admission, AdmissionStatusHistory

            admission = Admission.objects.filter(id=adm_id).first()
            if not admission:
                return {"success": False, "error": f"Admission {adm_id} not found."}
            if admission.status != 'payment_pending':
                return {"success": True, "processed": "ADM", "note": "Already processed."}

            admission.transaction_id       = rp_payment_id
            admission.payment_note         = f"Paid via Razorpay: {link_entity.get('id')}"
            admission.payment_submitted_at = timezone.now()
            admission.payment_amount       = amount_paid
            admission.razorpay_payment_id  = rp_payment_id
            admission.status               = 'approval_pending'
            admission.save(update_fields=[
                'transaction_id', 'payment_note', 'payment_submitted_at',
                'payment_amount', 'razorpay_payment_id', 'status', 'updated_at',
            ])
            AdmissionStatusHistory.objects.create(
                admission  = admission,
                status     = 'approval_pending',
                changed_by = None,
                note       = f"Payment auto-verified via Razorpay. Txn: {rp_payment_id}",
            )
            logger.info(f"[Razorpay] Admission {adm_id} moved to approval_pending.")

            # ── Auto-send payment confirmation (email + WhatsApp) ─────────
            try:
                send_admission_payment_notification(admission, amount_paid, rp_payment_id)
            except Exception as notify_err:
                logger.error(f"[Razorpay] ADM notification failed for {adm_id}: {notify_err}")

            return {"success": True, "processed": "ADM"}

        return {"success": True, "processed": "unknown", "reference_id": reference_id}

    except Exception as exc:
        logger.error(f"Razorpay process_payment_link_paid_event error: {exc}")
        return {"success": False, "error": str(exc)}


def process_refund_processed_event(payload: dict) -> dict:
    """
    Handle the 'refund.processed' Razorpay webhook event.
    Finds the local Payment by transaction_ref and marks/creates the Refund record.

    Returns:
        { "success": True, "refund_id": <local-refund-id> }
    """
    try:
        refund_entity = payload.get('payload', {}).get('refund', {}).get('entity', {})
        rp_payment_id = refund_entity.get('payment_id', '')
        rp_refund_id  = refund_entity.get('id', '')
        refund_amount = refund_entity.get('amount', 0) / 100

        from .models import Payment, Refund
        from .utils import update_student_fee_status

        local_payment = Payment.objects.filter(transaction_ref=rp_payment_id).first()
        if not local_payment:
            # Check if this was an admission payment that was refunded before enrollment/approval
            try:
                from onboarding.models import Admission, AdmissionStatusHistory
                admission = Admission.objects.filter(transaction_id=rp_payment_id).first()
                if admission:
                    admission.status = 'payment_pending'
                    admission.transaction_id = ''
                    admission.payment_note = f"Razorpay refund {rp_refund_id} processed."
                    admission.save(update_fields=['status', 'transaction_id', 'payment_note', 'updated_at'])
                    
                    AdmissionStatusHistory.objects.create(
                        admission=admission,
                        status='payment_pending',
                        changed_by=None,
                        note=f"Payment refunded via Razorpay. Txn: {rp_payment_id}, Refund: {rp_refund_id}",
                    )
                    logger.info(f"[Razorpay] Refund {rp_refund_id} processed for admission {admission.id}. Status reset to payment_pending.")
                    return {"success": True, "refund_id": "admission_refunded"}
            except Exception as e:
                logger.error(f"[Razorpay] Error processing admission refund: {e}")

            logger.warning(f"[Razorpay] refund.processed: no local payment or admission for {rp_payment_id}")
            return {"success": True, "note": "No matching local payment found — skipped."}

        refund, created = Refund.objects.get_or_create(
            payment = local_payment,
            defaults={
                'amount': refund_amount,
                'reason': f"Razorpay refund {rp_refund_id}",
                'status': 'completed',
            }
        )
        if not created and refund.status != 'completed':
            refund.status = 'completed'
            refund.save(update_fields=['status'])

        update_student_fee_status(local_payment.student_fee_id)
        logger.info(f"[Razorpay] Refund {rp_refund_id} processed for payment {rp_payment_id}.")
        return {"success": True, "refund_id": str(refund.id)}

    except Exception as exc:
        logger.error(f"Razorpay process_refund_processed_event error: {exc}")
        return {"success": False, "error": str(exc)}


def process_payment_link_cancelled_event(payload: dict) -> dict:
    """
    Handle 'payment_link.cancelled' and 'payment_link.expired' webhook events.
    Clears the payment link ID from the associated records if necessary.
    """
    try:
        link_entity   = payload.get('payload', {}).get('payment_link', {}).get('entity', {})
        reference_id  = link_entity.get('reference_id', '')
        link_id       = link_entity.get('id', '')

        # ── Admission flow ────────────────────────────────────────────────
        if reference_id.startswith('ADM_'):
            adm_id = reference_id.split('_')[1]
            from onboarding.models import Admission

            admission = Admission.objects.filter(id=adm_id).first()
            if admission and admission.razorpay_payment_link_id == link_id:
                admission.razorpay_payment_link = None
                admission.razorpay_payment_link_id = None
                admission.save(update_fields=['razorpay_payment_link', 'razorpay_payment_link_id'])
                logger.info(f"[Razorpay] Admission {adm_id} payment link {link_id} cancelled/expired, cleared from record.")
                return {"success": True, "processed": "ADM"}

        return {"success": True, "processed": "unknown", "reference_id": reference_id}

    except Exception as exc:
        logger.error(f"Razorpay process_payment_link_cancelled_event error: {exc}")
        return {"success": False, "error": str(exc)}
