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
from decimal import Decimal

import requests as http_requests
from requests.auth import HTTPBasicAuth
from django.conf import settings
from django.db import transaction
from django.db.models import Q

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
    upi_id=None,
    notes=None,
) -> dict:
    """
    Create a Razorpay Payment Link.

    Args:
        amount              – Amount in INR (int/float/Decimal).
        reference_id        – Unique reference string (max 40 chars).
        customer_name       – Student / payer full name.
        customer_email      – Customer email.
        customer_contact    – Customer phone (10-digit, no country code prefix needed).
        description         – Short description shown on the payment page.
        upi_id              – (Unused in API; UPI deep-link is built separately.)
        notes               – Optional dictionary of metadata key-value pairs (max 15 pairs).

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

    ref_str = str(reference_id or '')
    if len(ref_str) > 40:
        ref_str = ref_str[:40]

    payload = {
        "amount": _to_paise(amount),
        "currency": "INR",
        "accept_partial": False,
        "reference_id": ref_str,
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
    if notes and isinstance(notes, dict):
        payload["notes"] = {str(k): str(v)[:256] for k, v in notes.items()}

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


def send_admission_payment_notification(
    admission,
    amount_paid: float,
    rp_payment_id: str,
    *,
    is_partial: bool = False,
):
    """
    Send payment confirmation email + WhatsApp to the student (and parent if available)
    when a Razorpay payment event is received for an Admission (ADM_ flow).
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

        token_note = getattr(admission, 'token_payment_terms_note', None)
        token_notice_block = (
            f"\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"IMPORTANT NOTICE (REMAINING FEES):\n"
            f"{token_note}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        ) if token_note else ""
        payment_status = (
            "Partial Payment Received — Remaining Payment Pending"
            if is_partial
            else "Payment Received — Enrolled"
        )
        enrollment_message = (
            "Please complete the remaining payment to finish your enrollment."
            if is_partial
            else "Your enrollment is complete. Login credentials will be sent separately."
        )

        subject = f"Payment Receipt – ₹{amount_paid:,.0f} | Insight Institute"
        text_body = (
            f"Dear {student_name},\n\n"
            f"We have received your payment of ₹{amount_paid:,.2f} via Razorpay.\n\n"
            f"Receipt No     : {receipt_number}\n"
            f"Transaction ID : {rp_payment_id or 'N/A'}\n"
            f"Amount         : ₹{amount_paid:,.2f}\n"
            f"Date           : {receipt_date}\n"
            f"Status         : {payment_status}\n\n"
            f"Your official receipt is attached to this email. "
            f"{enrollment_message}"
            f"{token_notice_block}\n\n"
            f"Thank you,\nInsight Institute of Professional Studies"
        )
        template_context = {
            'student_name': student_name,
            'amount': f"{float(amount_paid):,.2f}",
            'receipt_number': receipt_number,
            'payment_mode': 'Razorpay (Online)',
            'transaction_ref': rp_payment_id or 'N/A',
            'payment_date': receipt_date,
            'token_note': token_note,
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
                wa_token_part = f"\n\n⚠️ *Important Notice:*\n{token_note}" if token_note else ""
                wa_caption = (
                    f"✅ *Payment Receipt — Insight Institute*\n"
                    f"Dear {student_name},\n\n"
                    f"Your payment of ₹{amount_paid:,.0f} has been received via Razorpay.\n"
                    f"Receipt No    : {receipt_number}\n"
                    f"Transaction ID: {rp_payment_id or 'N/A'}\n"
                    f"Date          : {receipt_date}\n\n"
                    f"{enrollment_message}"
                    f"{wa_token_part}\n\n"
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
                if pdf_public_url:
                    wa_caption += f"\n\n📄 Download receipt: {pdf_public_url}"

                for phone in phones:
                    try:
                        components = [{
                            "type": "body",
                            "parameters": [
                                {"type": "text", "text": student_name},
                                {"type": "text", "text": f"{float(amount_paid):,.2f}"},
                                {"type": "text", "text": receipt_number},
                                {"type": "text", "text": "Razorpay (Online)"},
                                {"type": "text", "text": rp_payment_id or "N/A"},
                            ]
                        }]
                        if pdf_public_url:
                            components.insert(0, {
                                "type": "header",
                                "parameters": [{
                                    "type": "document",
                                    "document": {
                                        "link": pdf_public_url,
                                        "filename": f"Receipt_{receipt_number}.pdf"
                                    }
                                }]
                            })

                        send_whatsapp_with_fallback(
                            to=phone,
                            template_name="payment_reciept_" if pdf_public_url else None,
                            language_code="en",
                            components=components if pdf_public_url else None,
                            fallback_body=wa_caption,
                        )
                        logger.info(f"[Razorpay] ADM WhatsApp receipt sent to {phone}")
                    except Exception as wa_err:
                        logger.error(f"[Razorpay] ADM WhatsApp failed to {phone}: {wa_err}")
        except Exception as wa_import_err:
            logger.error(f"[Razorpay] WhatsApp import failed: {wa_import_err}")

    except Exception as exc:
        logger.error(f"[Razorpay] send_admission_payment_notification error: {exc}", exc_info=True)


def transfer_payment_to_linked_account(payment_id: str, amount_in_inr: float, linked_account_id: str) -> bool:
    """
    Transfers funds from the primary Razorpay account to a specific Linked Account using Razorpay Route.
    """
    payload = {
        "transfers": [
            {
                "account": linked_account_id,
                "amount": int(amount_in_inr * 100),  # amount in paise
                "currency": "INR"
            }
        ]
    }
    try:
        resp = http_requests.post(
            f"https://api.razorpay.com/v1/payments/{payment_id}/transfers",
            json=payload,
            auth=_auth(),
            timeout=15,
        )
        if resp.status_code in (200, 201):
            logger.info(f"[Razorpay Route] Successfully routed payment {payment_id} to {linked_account_id}")
            return True
        else:
            logger.error(f"[Razorpay Route] Failed to route payment {payment_id}: {resp.text}")
            return False
    except Exception as e:
        logger.error(f"[Razorpay Route] Exception routing payment {payment_id}: {e}")
        return False


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
        amount_paid_paise = link_entity.get('amount_paid') or pay_entity.get('amount') or 0
        amount_paid   = Decimal(str(amount_paid_paise)) / Decimal('100')
        rp_payment_id = pay_entity.get('id', '') or link_entity.get('id', '')

        # ── StudentFee flow ───────────────────────────────────────────────
        if reference_id.startswith('SF_'):
            notes = link_entity.get('notes', {}) or pay_entity.get('notes', {}) or {}
            sf_id = notes.get('student_fee_id')
            if not sf_id:
                parts = reference_id.split('_')
                sf_id = parts[1] if len(parts) > 1 else None

            if not sf_id:
                return {"success": False, "error": "Could not parse SF id from reference_id or notes."}

            from .models import StudentFee, Payment
            from .utils import update_student_fee_status

            sf = None
            try:
                sf = StudentFee.objects.select_related('student').get(pk=sf_id)
            except (StudentFee.DoesNotExist, ValueError):
                std_id = notes.get('student_id')
                if std_id:
                    sf = StudentFee.objects.select_related('student').filter(student_id=std_id).order_by('-created_at').first()

            if not sf:
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

            # ── Route Transfer ───────────────────────────────────────────────
            try:
                from onboarding.models import Admission
                admission = Admission.objects.filter(email=sf.student.email).order_by('-submitted_at').first()
                if admission and admission.bank_account and admission.bank_account.razorpay_account_id:
                    transfer_payment_to_linked_account(rp_payment_id, amount_paid, admission.bank_account.razorpay_account_id)
            except Exception as e:
                logger.error(f"[Razorpay Route] Transfer failed for SF {sf_id}: {e}")

            return {"success": True, "processed": "SF", "payment_id": str(payment.id)}

        # ── Admission flow ────────────────────────────────────────────────
        elif reference_id.startswith('ADM_'):
            parts = reference_id.split('_', 2)
            if len(parts) < 2 or not parts[1]:
                return {"success": False, "error": f"Invalid admission reference_id: {reference_id}"}
            adm_id = parts[1]

            payment_amount_paise = pay_entity.get('amount')
            transaction_amount = (
                Decimal(str(payment_amount_paise)) / Decimal('100')
                if payment_amount_paise is not None
                else amount_paid
            )
            if transaction_amount <= 0 or not pay_entity.get('id'):
                return {
                    "success": False,
                    "error": "Razorpay admission event is missing a valid payment amount or payment ID.",
                }

            from onboarding.models import Admission
            from onboarding.utils import AdmissionService
            from auth_user.models import User as AuthUser
            from students.models import Student
            from students.utils import StudentService
            from .models import Payment, StudentFee
            from .services import send_payment_receipt
            from django.db.models import Sum

            event = payload.get('event')
            is_partial = event == 'payment_link.partially_paid'
            now = timezone.now()
            profile_creation_error = None

            with transaction.atomic():
                adm_lookup = Q(admission_code__iexact=str(adm_id).strip())
                if str(adm_id).strip().isdigit():
                    adm_lookup |= Q(id=int(str(adm_id).strip()))
                elif str(adm_id).strip().upper().startswith('IIPS-'):
                    num_part = str(adm_id).strip().split('-')[-1].lstrip('0')
                    if num_part.isdigit():
                        adm_lookup |= Q(id=int(num_part))
                admission = Admission.objects.select_for_update().filter(adm_lookup).first()
                if not admission:
                    return {"success": False, "error": f"Admission {adm_id} not found."}

                existing_payment = Payment.objects.filter(
                    admission=admission,
                    transaction_ref=rp_payment_id,
                ).first()
                is_new_transaction = existing_payment is None
                if existing_payment is None:
                    existing_payment = Payment.objects.filter(
                        admission=admission,
                        status='approval_pending',
                        payment_mode='online',
                        transaction_ref='',
                    ).order_by('-created_at').first()
                previous_total = Payment.objects.filter(
                    admission=admission,
                    status='verified',
                ).exclude(transaction_ref=rp_payment_id).aggregate(
                    total=Sum('amount'),
                )['total'] or Decimal('0')
                cumulative_paid = max(previous_total + transaction_amount, amount_paid)

                token_note = getattr(admission, 'token_payment_terms_note', None)
                payment_note = f"Paid via Razorpay: {link_entity.get('id')}"
                history_note = (
                    f"Payment auto-verified directly via Razorpay (no approval needed). "
                    f"Txn: {rp_payment_id}"
                )
                if token_note:
                    payment_note += f". {token_note}"
                    history_note += f". {token_note}"

                admission.transaction_id = rp_payment_id
                admission.payment_note = payment_note
                admission.payment_submitted_at = admission.payment_submitted_at or now
                admission.payment_amount = cumulative_paid
                admission.razorpay_payment_id = rp_payment_id
                if not is_partial:
                    admission.razorpay_link = None
                admission.save(update_fields=[
                    'transaction_id', 'payment_note', 'payment_submitted_at', 'payment_amount',
                    'razorpay_payment_id', 'updated_at', 'razorpay_link'
                ])

                student = Student.objects.filter(admission=admission).first()
                payment = existing_payment
                if not is_partial:
                    if admission.status != 'enrolled':
                        AdmissionService.update_status(
                            admission=admission,
                            new_status='enrolled',
                            note=history_note,
                            user=None,
                        )

                    student_user = student.user if student else AuthUser.objects.filter(
                        email__iexact=admission.email,
                        role='student',
                    ).first()
                    if not student_user:
                        try:
                            AdmissionService._create_user_accounts(admission)
                        except Exception as exc:
                            logger.error(
                                f"[Razorpay] Student account creation failed for admission {adm_id}: {exc}"
                            )
                        student_user = AuthUser.objects.filter(
                            email__iexact=admission.email,
                            role='student',
                        ).first()
                    if not student_user:
                        profile_creation_error = (
                            f"Student login account could not be created for admission {adm_id}."
                        )

                    if not student:
                        if student_user:
                            try:
                                student = StudentService.create_from_admission(
                                    admission=admission,
                                    user=student_user,
                                    acting_user=None,
                                )
                            except Exception as exc:
                                logger.error(
                                    f"[Razorpay] Student profile creation failed for admission {adm_id}: {exc}"
                                )
                                profile_creation_error = str(exc)
                        student = Student.objects.filter(admission=admission).first()
                    if not student and not profile_creation_error:
                        profile_creation_error = (
                            f"Student profile was not created for admission {adm_id}."
                        )

                    if payment is None:
                        payment = Payment.objects.filter(
                            admission=admission,
                            transaction_ref=rp_payment_id,
                        ).first()

                payment_created_here = payment is None
                if payment_created_here:
                    payment = Payment.objects.create(
                        admission=admission,
                        student=student,
                        amount=transaction_amount,
                        payment_mode='online',
                        transaction_ref=rp_payment_id,
                        status='verified',
                        verified_at=now,
                        payment_date=now.date(),
                        note=f"Auto-verified via Razorpay: {rp_payment_id}",
                    )
                else:
                    payment.admission = payment.admission or admission
                    payment.student = student or payment.student
                    payment.amount = transaction_amount
                    payment.payment_mode = 'online'
                    payment.transaction_ref = rp_payment_id
                    payment.status = 'verified'
                    payment.verified_at = payment.verified_at or now
                    payment.payment_date = now.date()
                    payment.note = f"Auto-verified via Razorpay: {rp_payment_id}"
                    payment.save()

                if student and not payment.student_fee_id:
                    student_fee = StudentFee.objects.filter(student=student).order_by('-created_at').first()
                    if student_fee:
                        payment.student_fee = student_fee
                        payment.save(update_fields=['student_fee', 'updated_at'])

                total_paid = Payment.objects.filter(
                    admission=admission,
                    status='verified',
                ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
                admission.payment_amount = total_paid
                admission.save(update_fields=['payment_amount', 'updated_at'])

                history = list(admission.payment_history or [])
                for entry in reversed(history):
                    if (
                        entry.get('event') == 'payment_link_created'
                        and entry.get('razorpay_payment_link_id') == link_entity.get('id')
                    ):
                        entry.update({
                            'status': 'partially_paid' if is_partial else 'paid',
                            'amount_paid': float(total_paid),
                            'last_payment_amount': float(transaction_amount),
                        })
                        break

                payment_event = 'payment_received' if is_partial else 'payment_approved'
                payment_history_entry = {
                    'event': payment_event,
                    'timestamp': now.isoformat(),
                    'payment_choice': 'online',
                    'amount': float(transaction_amount),
                    'amount_paid': float(total_paid),
                    'transaction_id': rp_payment_id,
                    'razorpay_payment_id': rp_payment_id,
                    'status': 'partially_paid' if is_partial else 'verified',
                    'level': 'auto',
                    'approver_role': 'system_razorpay',
                    'verified_by': 'Razorpay (Direct to Bank)',
                    'verified_at': now.isoformat(),
                    'date': now.date().isoformat(),
                    'note': history_note,
                }
                matching_entry = next(
                    (
                        entry for entry in reversed(history)
                        if entry.get('transaction_id') == rp_payment_id
                        or entry.get('razorpay_payment_id') == rp_payment_id
                    ),
                    None,
                )
                if matching_entry:
                    matching_entry.update(payment_history_entry)
                else:
                    history.append(payment_history_entry)
                admission.payment_history = history
                admission.save(update_fields=['payment_history', 'updated_at'])

            # ── Always dispatch receipt + notification even if student setup failed ──
            # Payment is verified regardless of profile creation status; the student
            # and parent must still receive their receipt email & WhatsApp.
            if is_new_transaction:
                receipt_sent = False
                if payment and not (getattr(payment, '_receipt_notified', None) is True):
                    try:
                        send_payment_receipt(payment)
                        receipt_sent = True
                    except Exception as exc:
                        logger.error(f"[Razorpay] Receipt dispatch failed for {rp_payment_id}: {exc}")

                # Only send admission-level notification as FALLBACK if
                # send_payment_receipt failed or payment record was missing,
                # OR for partial payments (which don't create a student yet).
                if not receipt_sent or is_partial:
                    try:
                        send_admission_payment_notification(
                            admission,
                            float(transaction_amount),
                            rp_payment_id,
                            is_partial=is_partial,
                        )
                    except Exception as notify_err:
                        logger.error(f"[Razorpay] ADM notification failed for {adm_id}: {notify_err}")

                try:
                    if admission.bank_account and admission.bank_account.razorpay_account_id:
                        transfer_payment_to_linked_account(
                            rp_payment_id,
                            transaction_amount,
                            admission.bank_account.razorpay_account_id,
                        )
                except Exception as exc:
                    logger.error(f"[Razorpay Route] Transfer failed for ADM {adm_id}: {exc}")

            if profile_creation_error:
                logger.error(
                    f"[Razorpay] Admission {adm_id} payment is verified, but student setup failed: "
                    f"{profile_creation_error}"
                )
                return {
                    "success": False,
                    "error": profile_creation_error,
                    "receipt_sent": is_new_transaction,
                    "payment_id": str(payment.id) if payment else None,
                }

            logger.info(
                f"[Razorpay] Admission {adm_id} payment {rp_payment_id} "
                f"processed ({'partial' if is_partial else 'paid'})."
            )
            return {"success": True, "processed": "ADM", "payment_id": str(payment.id)}

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

            adm_lookup = Q(admission_code__iexact=str(adm_id).strip())
            if str(adm_id).strip().isdigit():
                adm_lookup |= Q(id=int(str(adm_id).strip()))
            elif str(adm_id).strip().upper().startswith('IIPS-'):
                num_part = str(adm_id).strip().split('-')[-1].lstrip('0')
                if num_part.isdigit():
                    adm_lookup |= Q(id=int(num_part))
            admission = Admission.objects.filter(adm_lookup).first()
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
