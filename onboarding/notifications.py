"""
onboarding/notifications.py

Handles WhatsApp notification and interactive approval/rejection workflows
for admission fee payments using the Meta template 'payment_approve_reject'.

Template structure:
-------------------
Header: IMAGE (screenshot of payment)
Body:
    FEE PAYMENT VERIFICATION

    Student Details Student Name: {{1}} Admission ID: {{2}} Course Type: {{3}} Module: {{4}} Attempt: {{5}}

    Payment Details Payment Type: {{6}} Payment Mode: {{7}} Payment Amount: ₹{{8}} Transaction ID / Cheque No.: {{9}} Payment Submitted At: {{10}}

    Regards,
    Insight ERP

Buttons:
    - Approve (index 0, quick_reply: adm_pay_approve:<admission_id>)
    - Reject  (index 1, quick_reply: adm_pay_reject:<admission_id>)

2-Level Approval Flow:
----------------------
    Level 1: Accountant verifies payment (moves status to 'approved' and notifies Super Admin).
    Level 2: Super Admin final approval (moves status to 'enrolled', creates student & dispatches credentials).
"""
import logging
import re
from typing import Optional, Tuple, Dict, Any, List

from django.conf import settings
from django.utils import timezone
from django.db.models import Q

logger = logging.getLogger(__name__)

PAYMENT_APPROVER_ROLES = {'super_admin', 'accountant'}


def get_payment_screenshot_url(admission) -> str:
    """
    Returns an absolute, publicly accessible URL for the uploaded payment screenshot.
    Handles Azure Blob Storage, full URLs, and relative MEDIA_URL paths.
    """
    if not admission or not getattr(admission, 'payment_screenshot', None):
        return ""
    try:
        raw_val = str(getattr(admission.payment_screenshot, 'name', admission.payment_screenshot) or '')
        if raw_val.startswith("http://") or raw_val.startswith("https://"):
            return raw_val

        if hasattr(admission.payment_screenshot, 'url'):
            url = str(admission.payment_screenshot.url)
        else:
            url = str(admission.payment_screenshot)

        if not url:
            return ""

        if url.startswith("http://") or url.startswith("https://"):
            return url

        media_url = getattr(settings, 'MEDIA_URL', '')
        if media_url.startswith("http://") or media_url.startswith("https://"):
            return f"{media_url.rstrip('/')}/{url.lstrip('/')}"

        base_domain = getattr(
            settings,
            'BACKEND_BASE_URL',
            'https://insightinstitute-fufvf3dbe0grg2b3.centralindia-01.azurewebsites.net'
        ).rstrip('/')
        return f"{base_domain}/{url.lstrip('/')}"
    except Exception as e:
        logger.warning("[WA ADMISSION] Could not resolve payment screenshot url for admission %s: %s", getattr(admission, 'id', None), e)
        return ""


def build_payment_approve_reject_components(admission) -> Tuple[List[Dict[str, Any]], str]:
    """
    Builds Meta WhatsApp template components for 'payment_approve_reject'.
    Returns (components, fallback_body).
    """
    # 1. Student Name
    student_name = " ".join(f"{admission.first_name} {admission.surname}".split())[:60] or "Student"

    # 2. Admission ID
    admission_id_str = str(admission.id)

    # 3. Course Type
    course_type = " ".join(str(
        admission.get_course_display() if hasattr(admission, 'get_course_display') else admission.course or 'N/A'
    ).split())[:60]

    # 4. Module
    module = " ".join(str(
        admission.get_group_module_display() if hasattr(admission, 'get_group_module_display') else admission.group_module or 'N/A'
    ).split())[:60]

    # 5. Attempt
    attempt_str = f"{admission.get_batch_attempt_display() if hasattr(admission, 'get_batch_attempt_display') else admission.batch_attempt or ''} {admission.attempt_year or ''}".strip() or "N/A"
    attempt = " ".join(attempt_str.split())[:60]

    # 6. Payment Type
    payment_type = " ".join(str(
        admission.get_payment_type_display() if hasattr(admission, 'get_payment_type_display') else admission.payment_type or 'Full Payment'
    ).split())[:60]

    # 7. Payment Mode
    payment_mode = " ".join(str(
        admission.get_payment_choice_display() if hasattr(admission, 'get_payment_choice_display') else admission.payment_choice or 'Cheque'
    ).split())[:60]

    # 8. Payment Amount (formatted without currency symbol because body includes ₹{{8}})
    amt = admission.payment_amount or admission.total_fees or 0
    try:
        amt_float = float(amt)
        amt_str = f"{amt_float:,.0f}" if amt_float.is_integer() else f"{amt_float:,.2f}"
    except Exception:
        amt_str = str(amt)
    amt_str = " ".join(amt_str.split())[:30]

    # 9. Transaction ID / Cheque No.
    txn_id = " ".join(str(admission.transaction_id or 'N/A').split())[:60]

    # 10. Payment Submitted At
    sub_dt = admission.payment_submitted_at or admission.updated_at or timezone.now()
    try:
        submitted_at = sub_dt.strftime('%d-%b-%Y %I:%M %p')
    except Exception:
        submitted_at = str(sub_dt)[:19]
    submitted_at = " ".join(submitted_at.split())[:60]

    PLACEHOLDER_RECEIPT_URL = (
        "https://insightinstitute-fufvf3dbe0grg2b3.centralindia-01.azurewebsites.net"
        "/static/images/payment_receipt_placeholder.png"
    )

    # Resolve screenshot URL
    screenshot_url = get_payment_screenshot_url(admission)

    # WhatsApp Cloud API template headers of type IMAGE only accept JPEG and PNG.
    # PDFs and other formats must fall back to the placeholder image in the header,
    # with the actual proof URL included in the body/fallback text.
    header_image_url = screenshot_url
    if not header_image_url:
        header_image_url = PLACEHOLDER_RECEIPT_URL
    else:
        clean_path = header_image_url.split('?')[0].lower()
        if not (clean_path.endswith('.jpg') or clean_path.endswith('.jpeg') or clean_path.endswith('.png')):
            header_image_url = PLACEHOLDER_RECEIPT_URL

    components: List[Dict[str, Any]] = [
        {
            "type": "header",
            "parameters": [
                {
                    "type": "image",
                    "image": {
                        "link": header_image_url
                    }
                }
            ]
        },
        {
            "type": "body",
            "parameters": [
                {"type": "text", "text": student_name},       # {{1}}
                {"type": "text", "text": admission_id_str},    # {{2}}
                {"type": "text", "text": course_type},        # {{3}}
                {"type": "text", "text": module},             # {{4}}
                {"type": "text", "text": attempt},            # {{5}}
                {"type": "text", "text": payment_type},        # {{6}}
                {"type": "text", "text": payment_mode},        # {{7}}
                {"type": "text", "text": amt_str},            # {{8}}
                {"type": "text", "text": txn_id},             # {{9}}
                {"type": "text", "text": submitted_at},       # {{10}}
            ]
        },
        {
            "type": "button",
            "sub_type": "quick_reply",
            "index": "0",
            "parameters": [{"type": "payload", "payload": f"adm_pay_approve:{admission.id}"}]
        },
        {
            "type": "button",
            "sub_type": "quick_reply",
            "index": "1",
            "parameters": [{"type": "payload", "payload": f"adm_pay_reject:{admission.id}"}]
        }
    ]

    fallback_body = (
        f"FEE PAYMENT VERIFICATION\n\n"
        f"Student Details\n"
        f"• Student Name: {student_name}\n"
        f"• Admission ID: {admission_id_str}\n"
        f"• Course Type: {course_type}\n"
        f"• Module: {module}\n"
        f"• Attempt: {attempt}\n\n"
        f"Payment Details\n"
        f"• Payment Type: {payment_type}\n"
        f"• Payment Mode: {payment_mode}\n"
        f"• Payment Amount: ₹{amt_str}\n"
        f"• Transaction ID / Cheque No.: {txn_id}\n"
        f"• Payment Submitted At: {submitted_at}\n\n"
        f"Proof Screenshot: {screenshot_url or 'N/A'}\n\n"
        f"Reply with:\n"
        f"- APPROVE {admission_id_str} to approve\n"
        f"- REJECT {admission_id_str} to reject\n\n"
        f"Regards,\n"
        f"Insight ERP"
    )

    return components, fallback_body


def send_payment_verification_whatsapp(admission, level: int = 1, approver_user=None):
    """
    Sends WhatsApp payment verification notification using 'payment_approve_reject' template.
      - level 1: Sent to Accountants (for initial verification)
      - level 2: Sent to Super Admins (for final enrollment approval)
    """
    from chat.notifications import send_whatsapp_with_fallback
    from auth_user.models import User

    if approver_user:
        recipients = [approver_user]
    else:
        target_role = 'accountant' if level == 1 else 'super_admin'
        qs = User.objects.filter(role=target_role, is_active=True)

        if getattr(admission, 'branch', None) and admission.branch.organization:
            scoped_qs = qs.filter(branch__organization=admission.branch.organization)
            if scoped_qs.exists():
                qs = scoped_qs

        recipients = list(qs)

        # If level 1 has no active accountants with phone, fallback to super_admin
        if level == 1 and not any(getattr(u, 'phone', None) for u in recipients):
            logger.warning("[WA ADMISSION] No accountant found with phone number for admission %s. Falling back to super_admin.", admission.id)
            recipients = list(User.objects.filter(role='super_admin', is_active=True))

    components, fallback_body = build_payment_approve_reject_components(admission)

    for user in recipients:
        phone = getattr(user, 'phone', None)
        if not phone:
            continue
        try:
            send_whatsapp_with_fallback(
                to=phone,
                template_name="payment_approve_reject",
                language_code="en",
                components=components,
                fallback_body=fallback_body,
                user_id=str(user.id),
            )
            logger.info(
                "[WA ADMISSION] Sent payment_approve_reject (Level %s) to %s (%s) for admission %s",
                level, getattr(user, 'name', user.username), phone, admission.id
            )
        except Exception as exc:
            logger.error(
                "[WA ADMISSION] Failed to send payment_approve_reject to %s: %s",
                user.id, exc
            )


def parse_admission_payment_payload(payload_str: str, text_str: str = "") -> Tuple[Optional[str], Optional[int]]:
    """
    Parses action ('approve' or 'reject') and admission_id from incoming WhatsApp message.
    Supports quick_reply button payloads:
      - adm_pay_approve:<id>
      - adm_pay_reject:<id>
      - payment_approve:<id>
      - pay_approve:<id>
    Also supports text replies:
      - "APPROVE 123" / "REJECT 123"
      - "APPROVE ADMISSION 123"
    """
    s = str(payload_str or "").strip()
    t = str(text_str or "").strip()

    action = None
    adm_id_str = None

    # Check button payload formats
    for prefix in ("adm_pay_approve:", "payment_approve:", "pay_approve:", "adm_pay_approve_", "approve:", "approve_"):
        if s.startswith(prefix):
            action = "approve"
            adm_id_str = s[len(prefix):]
            break

    if not action:
        for prefix in ("adm_pay_reject:", "payment_reject:", "pay_reject:", "adm_pay_reject_", "reject:", "reject_"):
            if s.startswith(prefix):
                action = "reject"
                adm_id_str = s[len(prefix):]
                break

    # Check generic colon separation: e.g. "adm_pay:approve:123"
    if not action and ":" in s:
        parts = s.split(":")
        if len(parts) >= 2:
            first = parts[0].lower()
            last = parts[-1].strip()
            if "approve" in first or (len(parts) > 2 and "approve" in parts[1].lower()):
                action = "approve"
                adm_id_str = last
            elif "reject" in first or (len(parts) > 2 and "reject" in parts[1].lower()):
                action = "reject"
                adm_id_str = last

    # Check plain text commands
    if not action and t:
        upper_t = t.upper()
        match_approve = re.search(r'\bAPPROVE\b.*?\b(\d+)\b', upper_t)
        match_reject = re.search(r'\bREJECT\b.*?\b(\d+)\b', upper_t)
        if match_approve:
            action = "approve"
            adm_id_str = match_approve.group(1)
        elif match_reject:
            action = "reject"
            adm_id_str = match_reject.group(1)

    if adm_id_str:
        try:
            adm_id = int(str(adm_id_str).strip())
            return action, adm_id
        except (ValueError, TypeError):
            return None, None

    return None, None


def handle_admission_payment_whatsapp_approval(sender_wa_id: str, payload_str: str, text_str: str = "") -> bool:
    """
    Webhook handler for WhatsApp button and text interactions with 'payment_approve_reject'.
    Restricts actions to Accountant (Level 1) and Super Admin (Level 2).
    """
    action, admission_id = parse_admission_payment_payload(payload_str, text_str)
    if not action or not admission_id:
        return False

    from auth_user.models import User
    from onboarding.models import Admission
    from onboarding.utils import AdmissionService
    from chat.notifications import send_whatsapp_text

    # 1. Resolve approver user by phone number
    phone_clean = str(sender_wa_id or '').strip()
    if phone_clean.startswith('+'):
        phone_clean = phone_clean[1:]
    phone_10 = phone_clean[2:] if (phone_clean.startswith('91') and len(phone_clean) == 12) else phone_clean

    candidates = list(User.objects.filter(
        Q(phone=sender_wa_id) |
        Q(phone=phone_clean) |
        Q(phone=phone_10) |
        Q(phone=f'+91{phone_10}') |
        Q(phone=f'91{phone_10}') |
        Q(phone=f'+{phone_clean}'),
        is_active=True
    ))

    if not candidates:
        logger.warning("[WA ADMISSION] No active user found for sender_wa_id=%s", sender_wa_id)
        send_whatsapp_text(
            to=sender_wa_id,
            body="Unauthorized: Your phone number is not registered as an authorized approver."
        )
        return True

    # Find candidate with approver role
    approver = None
    for c in candidates:
        if c.role in PAYMENT_APPROVER_ROLES or getattr(c, 'is_superuser', False):
            approver = c
            break

    if not approver:
        logger.warning("[WA ADMISSION] User %s is not an authorized approver (role=%s)", candidates[0].id, candidates[0].role)
        send_whatsapp_text(
            to=sender_wa_id,
            body="Unauthorized: Payment approval requires Accountant (Level 1) or Super Admin (Level 2) role."
        )
        return True

    # 2. Fetch admission
    try:
        admission = Admission.objects.get(id=admission_id)
    except Admission.DoesNotExist:
        logger.warning("[WA ADMISSION] Admission id=%s not found.", admission_id)
        send_whatsapp_text(to=sender_wa_id, body=f"Admission #{admission_id} not found.")
        return True

    approver_name = getattr(approver, 'name', None) or approver.username
    role = approver.role
    is_superuser = getattr(approver, 'is_superuser', False)

    # 3. Handle REJECT action
    if action == "reject":
        if admission.status == 'enrolled':
            send_whatsapp_text(
                to=sender_wa_id,
                body=f"Admission #{admission.id} ({admission.first_name}) is already enrolled and cannot be rejected."
            )
            return True

        reject_note = f"Payment rejected via WhatsApp by {approver_name} ({role})."
        AdmissionService.update_status(
            admission=admission,
            new_status='rejected',
            note=reject_note,
            user=approver,
        )
        from fees.models import Payment
        Payment.objects.filter(admission=admission).exclude(status__in=['verified', 'refunded']).update(
            status='rejected',
            note=reject_note,
        )
        admission.add_payment_history_entry('payment_rejected', {
            'payment_choice': admission.payment_choice,
            'amount': float(admission.payment_amount or admission.total_fees or 0),
            'transaction_id': admission.transaction_id,
            'status': 'rejected',
            'rejected_by': approver_name,
            'rejected_at': timezone.now().isoformat(),
            'date': timezone.now().date().isoformat(),
            'note': reject_note,
        })
        send_whatsapp_text(
            to=sender_wa_id,
            body=f"❌ Payment for admission #{admission.id} ({admission.first_name} {admission.surname}) has been REJECTED by {approver_name}."
        )
        logger.info("[WA ADMISSION] Admission %s rejected via WhatsApp by %s", admission.id, approver.id)
        return True

    # 4. Handle APPROVE action
    if action == "approve":
        if admission.status == 'enrolled':
            send_whatsapp_text(
                to=sender_wa_id,
                body=f"Admission #{admission.id} ({admission.first_name} {admission.surname}) is already enrolled."
            )
            return True

        if admission.status == 'rejected':
            send_whatsapp_text(
                to=sender_wa_id,
                body=f"Admission #{admission.id} is marked as rejected. Please reset its status in ERP before approving."
            )
            return True

        # Check approval level:
        # LEVEL 1: Pending accountant verification
        if admission.status in ('approval_pending', 'payment_submitted', 'payment_pending'):
            if role == 'accountant' or is_superuser:
                level1_note = f"Level 1 payment approval completed via WhatsApp by Accountant {approver_name}."
                AdmissionService.update_status(
                    admission=admission,
                    new_status='approved',
                    note=level1_note,
                    user=approver,
                )
                admission.add_payment_history_entry('payment_verified', {
                    'payment_choice': admission.payment_choice,
                    'amount': float(admission.payment_amount or admission.total_fees or 0),
                    'transaction_id': admission.transaction_id,
                    'status': 'level_1_approved',
                    'level': 1,
                    'approver_role': 'accountant',
                    'verified_by': approver_name,
                    'verified_at': timezone.now().isoformat(),
                    'date': timezone.now().date().isoformat(),
                    'note': level1_note,
                })

                # Synchronize Payment status to level_1_approved
                from fees.models import Payment
                payment = Payment.objects.filter(admission=admission).first()
                if payment:
                    payment.status = 'level_1_approved'
                    payment.verified_by = approver
                    payment.note = level1_note
                    payment.save(update_fields=['status', 'verified_by', 'note', 'updated_at'])
                else:
                    mapped_mode = 'cheque' if str(admission.payment_choice).lower() in ('cheque', 'check') else ('cash' if str(admission.payment_choice).lower() == 'cash' else 'online')
                    Payment.objects.create(
                        admission=admission,
                        amount=admission.payment_amount or admission.total_fees or 0,
                        payment_mode=mapped_mode,
                        transaction_ref=admission.transaction_id or '',
                        payment_proof=admission.payment_screenshot,
                        status='level_1_approved',
                        verified_by=approver,
                        payment_date=timezone.now().date(),
                        note=level1_note,
                    )

                send_whatsapp_text(
                    to=sender_wa_id,
                    body=(
                        f"✅ Level 1 payment approval completed for admission #{admission.id} "
                        f"({admission.first_name} {admission.surname}).\n\n"
                        f"Status is now 'Approved'. Notification dispatched to Super Admin for Level 2 (final) approval."
                    )
                )

                # Send Level 2 template notification to Super Admins
                try:
                    send_payment_verification_whatsapp(admission, level=2)
                except Exception as exc:
                    logger.error("[WA ADMISSION] Failed to dispatch Level 2 WhatsApp notification: %s", exc)

                return True

            elif role == 'super_admin':
                # Super Admin approving directly: complete both Level 1 & Level 2 as executive override
                super_note = f"Super Admin final approval & enrollment completed via WhatsApp by {approver_name}."
                AdmissionService.update_status(
                    admission=admission,
                    new_status='enrolled',
                    note=super_note,
                    user=approver,
                )

                from auth_user.models import User as AuthUser
                student_user = AuthUser.objects.filter(email__iexact=admission.email, role='student').first()
                adm_no = f"ADM-{admission.id}"
                if student_user:
                    try:
                        from students.utils import StudentService
                        student = StudentService.create_from_admission(admission=admission, user=student_user, acting_user=approver)
                        adm_no = student.admission_number
                    except Exception as exc:
                        logger.error("[WA ADMISSION] StudentService.create_from_admission error: %s", exc)

                admission.add_payment_history_entry('payment_approved', {
                    'payment_choice': admission.payment_choice,
                    'amount': float(admission.payment_amount or admission.total_fees or 0),
                    'transaction_id': admission.transaction_id,
                    'status': 'verified',
                    'level': 2,
                    'approver_role': 'super_admin',
                    'verified_by': approver_name,
                    'verified_at': timezone.now().isoformat(),
                    'date': timezone.now().date().isoformat(),
                    'note': super_note,
                })

                # Synchronize Payment status to verified and link student
                from fees.models import Payment
                from fees.services import send_payment_receipt
                payment = Payment.objects.filter(admission=admission).first()
                if payment:
                    payment.status = 'verified'
                    if student_user and 'student' in locals() and student:
                        payment.student = student
                    payment.verified_by = approver
                    payment.verified_at = timezone.now()
                    payment.note = super_note
                    payment.save(update_fields=['status', 'student', 'verified_by', 'verified_at', 'note', 'updated_at'])
                    try:
                        send_payment_receipt(payment)
                    except Exception as exc:
                        logger.error("[WA ADMISSION] Failed to send receipt: %s", exc)
                else:
                    mapped_mode = 'cheque' if str(admission.payment_choice).lower() in ('cheque', 'check') else ('cash' if str(admission.payment_choice).lower() == 'cash' else 'online')
                    payment = Payment.objects.create(
                        admission=admission,
                        student=student if ('student' in locals() and student) else None,
                        amount=admission.payment_amount or admission.total_fees or 0,
                        payment_mode=mapped_mode,
                        transaction_ref=admission.transaction_id or '',
                        payment_proof=admission.payment_screenshot,
                        status='verified',
                        recorded_by=approver,
                        verified_by=approver,
                        verified_at=timezone.now(),
                        payment_date=timezone.now().date(),
                        note=super_note,
                    )
                    try:
                        send_payment_receipt(payment)
                    except Exception as exc:
                        logger.error("[WA ADMISSION] Failed to send receipt: %s", exc)

                send_whatsapp_text(
                    to=sender_wa_id,
                    body=(
                        f"🎉 Final approval completed! Admission #{admission.id} "
                        f"({admission.first_name} {admission.surname}) is now enrolled.\n\n"
                        f"Admission No: {adm_no}\n"
                        f"Student login credentials have been dispatched."
                    )
                )
                return True

        # LEVEL 2: Admission is in 'approved' status (waiting for Super Admin)
        if admission.status == 'approved':
            if role != 'super_admin' and not is_superuser:
                send_whatsapp_text(
                    to=sender_wa_id,
                    body=(
                        f"Admission #{admission.id} has already completed Level 1 approval. "
                        f"Level 2 (final) approval must be performed by a Super Admin."
                    )
                )
                return True

            final_note = f"Level 2 final approval completed via WhatsApp by Super Admin {approver_name}."
            AdmissionService.update_status(
                admission=admission,
                new_status='enrolled',
                note=final_note,
                user=approver,
            )

            from auth_user.models import User as AuthUser
            student_user = AuthUser.objects.filter(email__iexact=admission.email, role='student').first()
            adm_no = f"ADM-{admission.id}"
            if student_user:
                try:
                    from students.utils import StudentService
                    student = StudentService.create_from_admission(admission=admission, user=student_user, acting_user=approver)
                    adm_no = student.admission_number
                except Exception as exc:
                    logger.error("[WA ADMISSION] StudentService.create_from_admission error: %s", exc)

            admission.add_payment_history_entry('payment_approved', {
                'payment_choice': admission.payment_choice,
                'amount': float(admission.payment_amount or admission.total_fees or 0),
                'transaction_id': admission.transaction_id,
                'status': 'verified',
                'level': 2,
                'approver_role': 'super_admin',
                'verified_by': approver_name,
                'verified_at': timezone.now().isoformat(),
                'date': timezone.now().date().isoformat(),
                'note': final_note,
            })

            # Synchronize Payment status to verified and link student
            from fees.models import Payment
            from fees.services import send_payment_receipt
            payment = Payment.objects.filter(admission=admission).first()
            if payment:
                payment.status = 'verified'
                if student_user and 'student' in locals() and student:
                    payment.student = student
                payment.verified_by = approver
                payment.verified_at = timezone.now()
                payment.note = final_note
                payment.save(update_fields=['status', 'student', 'verified_by', 'verified_at', 'note', 'updated_at'])
                try:
                    send_payment_receipt(payment)
                except Exception as exc:
                    logger.error("[WA ADMISSION] Failed to send receipt: %s", exc)
            else:
                mapped_mode = 'cheque' if str(admission.payment_choice).lower() in ('cheque', 'check') else ('cash' if str(admission.payment_choice).lower() == 'cash' else 'online')
                payment = Payment.objects.create(
                    admission=admission,
                    student=student if ('student' in locals() and student) else None,
                    amount=admission.payment_amount or admission.total_fees or 0,
                    payment_mode=mapped_mode,
                    transaction_ref=admission.transaction_id or '',
                    payment_proof=admission.payment_screenshot,
                    status='verified',
                    recorded_by=approver,
                    verified_by=approver,
                    verified_at=timezone.now(),
                    payment_date=timezone.now().date(),
                    note=final_note,
                )
                try:
                    send_payment_receipt(payment)
                except Exception as exc:
                    logger.error("[WA ADMISSION] Failed to send receipt: %s", exc)

            send_whatsapp_text(
                to=sender_wa_id,
                body=(
                    f"🎉 Level 2 final approval completed! Admission #{admission.id} "
                    f"({admission.first_name} {admission.surname}) is now enrolled.\n\n"
                    f"Admission No: {adm_no}\n"
                    f"Student profile created & login credentials dispatched."
                )
            )
            logger.info("[WA ADMISSION] Admission %s enrolled via WhatsApp by Super Admin %s", admission.id, approver.id)
            return True

    return False
