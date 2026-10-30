import logging
from django.utils import timezone
from django.db.models import Q
from django.conf import settings

logger = logging.getLogger(__name__)

# Strictly authorized roles for reimbursement approvals
REIMBURSEMENT_APPROVER_ROLES = {'super_admin', 'accountant'}


def is_super_admin_user(u):
    if not u:
        return False
    if getattr(u, 'is_superuser', False):
        return True
    from core.utils import get_user_role
    u_role = get_user_role(u)
    if u_role == 'super_admin':
        return True
    add_roles = getattr(u, 'additional_roles', None) or []
    return 'super_admin' in add_roles


def is_accountant_user(u):
    if not u:
        return False
    from core.utils import get_user_role
    u_role = get_user_role(u)
    if u_role == 'accountant':
        return True
    add_roles = getattr(u, 'additional_roles', None) or []
    return 'accountant' in add_roles



def get_reimbursement_proof_url(reimbursement):
    """
    Returns an absolute, publicly accessible URL for the uploaded proof document.
    Handles Azure Blob Storage, full URLs, and relative MEDIA_URL paths.
    """
    if not reimbursement or not getattr(reimbursement, 'proof', None):
        return ""
    try:
        url = str(reimbursement.proof.url)
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
        logger.warning("[WA REIMB] Could not resolve proof url for claim %s: %s", getattr(reimbursement, 'id', None), e)
        return ""


def send_reimbursement_whatsapp_notification(reimbursement, approver, note_prefix=None):
    """
    Sends WhatsApp notification with template quick-reply buttons (Approve / Reject)
    using the approved Meta template 'reimbursement_claim_' to an authorized approver (Super Admin or Accountant).
    Includes the uploaded document/receipt URL in parameter {{5}} (Description).
    Parameters are sanitized to ensure no newlines exist, strictly preventing Meta Error 132018.
    """
    if not approver or not getattr(approver, 'phone', None):
        return

    from chat.notifications import send_whatsapp_with_fallback

    raw_applicant_name = getattr(reimbursement.user, 'name', None) or getattr(reimbursement.user, 'email', 'Staff Member')
    applicant_name = " ".join(str(raw_applicant_name).split())[:60]

    raw_title = reimbursement.title or 'Expense Claim'
    title_text = " ".join(str(raw_title).split())[:60]

    amount_str = f"{reimbursement.amount:.2f}" if reimbursement.amount is not None else "0.00"
    expense_date_str = str(reimbursement.expense_date or timezone.now().date())

    raw_desc = " ".join(str(reimbursement.description or '').split())
    proof_url = get_reimbursement_proof_url(reimbursement)

    desc_parts = []
    if note_prefix:
        desc_parts.append(str(note_prefix).strip())
    if raw_desc:
        desc_parts.append(raw_desc[:200])
    if proof_url:
        desc_parts.append(f"Doc: {proof_url}")

    if desc_parts:
        description_text = " | ".join(desc_parts)[:300]
    else:
        description_text = 'No description provided'

    # Ensure strictly single line for Meta template body parameters
    description_text = " ".join(description_text.split())

    notif_body = (
        f"Reimbursement Claim: {applicant_name} submitted a claim for '{title_text}' (₹{amount_str}) on {expense_date_str}. "
        f"Description: {description_text}"
    )

    components = [
        {
            "type": "body",
            "parameters": [
                {"type": "text", "text": str(applicant_name)},
                {"type": "text", "text": str(title_text)},
                {"type": "text", "text": str(amount_str)},
                {"type": "text", "text": str(expense_date_str)},
                {"type": "text", "text": str(description_text)},
            ]
        },
        {
            "type": "button",
            "sub_type": "quick_reply",
            "index": "0",
            "parameters": [{"type": "payload", "payload": f"reimb_approve:{reimbursement.id}"}]
        },
        {
            "type": "button",
            "sub_type": "quick_reply",
            "index": "1",
            "parameters": [{"type": "payload", "payload": f"reimb_reject:{reimbursement.id}"}]
        }
    ]

    try:
        send_whatsapp_with_fallback(
            to=approver.phone,
            template_name="reimbursement_claim_",
            language_code="en",
            components=components,
            fallback_body=notif_body,
            user_id=str(approver.id),
        )
        logger.info("[WA REIMB] Sent reimbursement_claim_ to %s (%s) for claim %s", approver.name, approver.phone, reimbursement.id)
    except Exception as e:
        logger.error("[WA REIMB] Failed to send reimbursement_claim_ to %s: %s", approver.id, e)

def send_reimbursement_update_whatsapp_notification(reimbursement, approver, old_amount=None):
    """
    Sends WhatsApp notification to an approver when a pending reimbursement claim's
    amount is updated by the claimant.

    Uses the Meta template 'reimbursement_claim_update_' which has the same body
    parameters and quick-reply buttons (Approve / Reject) as 'reimbursement_claim_'.

    Parameters (same order as reimbursement_claim_):
        {{1}} applicant_name
        {{2}} title
        {{3}} amount  (new amount, with old amount noted in description)
        {{4}} expense_date
        {{5}} description  (includes old amount context + proof URL)
    Buttons:
        index 0 -> quick_reply payload: reimb_approve:<uuid>
        index 1 -> quick_reply payload: reimb_reject:<uuid>
    """
    if not approver or not getattr(approver, 'phone', None):
        return

    from chat.notifications import send_whatsapp_with_fallback

    raw_applicant_name = getattr(reimbursement.user, 'name', None) or getattr(reimbursement.user, 'email', 'Staff Member')
    applicant_name = " ".join(str(raw_applicant_name).split())[:60]

    title_text = " ".join(str(reimbursement.title or 'Expense Claim').split())[:60]
    amount_str = f"{reimbursement.amount:.2f}" if reimbursement.amount is not None else "0.00"
    expense_date_str = str(reimbursement.expense_date or timezone.now().date())

    proof_url = get_reimbursement_proof_url(reimbursement)
    raw_desc = " ".join(str(reimbursement.description or '').split())

    # Build description parameter — include old amount context + proof link
    desc_parts = []
    if old_amount is not None:
        old_fmt = f"{old_amount:.2f}"
        desc_parts.append(f"Amount updated from Rs.{old_fmt} to Rs.{amount_str}")
    if raw_desc:
        desc_parts.append(raw_desc[:150])
    if proof_url:
        desc_parts.append(f"Doc: {proof_url}")
    description_text = " | ".join(desc_parts)[:300] if desc_parts else "No description provided"
    description_text = " ".join(description_text.split())  # ensure single-line

    fallback_body = (
        f"[UPDATED CLAIM] {applicant_name} updated their reimbursement claim '{title_text}' "
        f"(Rs.{amount_str}) on {expense_date_str}. "
        f"{description_text}"
    )

    components = [
        {
            "type": "body",
            "parameters": [
                {"type": "text", "text": applicant_name},    # {{1}}
                {"type": "text", "text": title_text},         # {{2}}
                {"type": "text", "text": amount_str},         # {{3}}
                {"type": "text", "text": expense_date_str},   # {{4}}
                {"type": "text", "text": description_text},   # {{5}}
            ]
        },
        {
            "type": "button",
            "sub_type": "quick_reply",
            "index": "0",
            "parameters": [{"type": "payload", "payload": f"reimb_approve:{reimbursement.id}"}]
        },
        {
            "type": "button",
            "sub_type": "quick_reply",
            "index": "1",
            "parameters": [{"type": "payload", "payload": f"reimb_reject:{reimbursement.id}"}]
        },
    ]

    try:
        send_whatsapp_with_fallback(
            to=approver.phone,
            template_name="reimbursement_claim_update_",
            language_code="en",
            components=components,
            fallback_body=fallback_body,
            user_id=str(approver.id),
        )
        logger.info(
            "[WA REIMB] Sent reimbursement_claim_update_ to %s (%s) for claim %s",
            getattr(approver, 'name', approver.id), approver.phone, reimbursement.id
        )
    except Exception as e:
        logger.error("[WA REIMB] Failed to send reimbursement_claim_update_ to %s: %s", approver.id, e)



def send_reimbursement_status_whatsapp_to_applicant(reimbursement, status_action, reviewer_name="Admin"):
    """
    Sends WhatsApp notification to the claim applicant using the approved 'reimbursement_status_update_' template.
    """
    applicant = getattr(reimbursement, 'user', None)
    if not applicant or not getattr(applicant, 'phone', None):
        return

    from chat.notifications import send_whatsapp_with_fallback

    applicant_display = " ".join(str(getattr(applicant, 'name', None) or 'Staff Member').split())[:60]
    title = " ".join(str(reimbursement.title or 'Expense Claim').split())[:60]
    amount = f"{reimbursement.amount:.2f}" if reimbursement.amount is not None else "0.00"
    status_str = "approved" if status_action == "approved" else "rejected"
    reviewer = " ".join(str(reviewer_name or 'Admin').split())[:60]

    if status_action == 'approved':
        remarks = "Amount will be credited in monthly payroll"
    else:
        raw_reason = str(reimbursement.rejection_reason or 'No reason provided')
        remarks = " ".join(raw_reason.split())[:150] or "No reason provided"

    fallback_body = (
        f"Hello {applicant_display},\n\n"
        f"Your reimbursement claim for *{title}* (₹{amount}) has been *{status_str.upper()}* by {reviewer}.\n"
        f"Remarks: {remarks}\n\nThank You!"
    )

    components = [
        {
            "type": "body",
            "parameters": [
                {"type": "text", "text": applicant_display},
                {"type": "text", "text": title},
                {"type": "text", "text": str(amount)},
                {"type": "text", "text": status_str},
                {"type": "text", "text": reviewer},
                {"type": "text", "text": remarks},
            ]
        }
    ]

    try:
        send_whatsapp_with_fallback(
            to=applicant.phone,
            template_name="reimbursement_status_update_",
            language_code="en",
            components=components,
            fallback_body=fallback_body,
            user_id=str(applicant.id),
        )
        logger.info("[WA REIMB] Sent reimbursement_status_update_ (%s) to applicant %s (%s)", status_str, applicant_display, applicant.phone)
    except Exception as e:
        logger.error("[WA REIMB] Failed to send status update to applicant %s: %s", applicant.id, e)


def parse_reimbursement_payload(payload_str, text_str=""):
    """
    Parses payload string (and optional text) to extract reimbursement action and UUID.
    Returns (action, reimbursement_id) or (None, None).
    """
    if not payload_str and not text_str:
        return None, None

    action = None
    reimb_id = None

    candidates = [str(payload_str or "").strip(), str(text_str or "").strip()]
    for s in candidates:
        if not s:
            continue
        s_lower = s.lower()
        if s_lower.startswith("reimb_approve:") or s_lower.startswith("reimbursement_approve:"):
            action = "approve"
            reimb_id = s.split(":", 1)[1].strip()
            break
        elif s_lower.startswith("reimb_reject:") or s_lower.startswith("reimbursement_reject:"):
            action = "reject"
            reimb_id = s.split(":", 1)[1].strip()
            break
        elif s_lower.startswith("reimb_approve_") or s_lower.startswith("reimbursement_approve_") or s_lower.startswith("approve_reimb_"):
            action = "approve"
            reimb_id = s.split("_", 2)[-1].strip()
            break
        elif s_lower.startswith("reimb_reject_") or s_lower.startswith("reimbursement_reject_") or s_lower.startswith("reject_reimb_"):
            action = "reject"
            reimb_id = s.split("_", 2)[-1].strip()
            break
        elif ":" in s and ("reimb" in s_lower or "reimbursement" in s_lower):
            parts = s.split(":")
            if len(parts) >= 2:
                if "approve" in parts[0].lower():
                    action = "approve"
                    reimb_id = parts[-1].strip()
                    break
                elif "reject" in parts[0].lower():
                    action = "reject"
                    reimb_id = parts[-1].strip()
                    break
        elif s_lower.startswith("approve") or s_lower.startswith("reject"):
            for prefix, act in [("approve", "approve"), ("reject", "reject")]:
                if s_lower.startswith(prefix):
                    remainder = s[len(prefix):].strip(" :_-#")
                    if remainder:
                        action = act
                        reimb_id = remainder
                        break
            if action:
                break

    if reimb_id:
        try:
            import uuid
            uuid_obj = uuid.UUID(reimb_id.strip())
            reimb_id = str(uuid_obj)
        except (ValueError, TypeError):
            reimb_id = None

    return action, reimb_id


def handle_reimbursement_whatsapp_approval(sender_wa_id, payload_str, text_str=""):
    """
    Handles approver action (Approve or Reject) for a Reimbursement claim
    triggered via WhatsApp template Quick Reply buttons.
    Strictly restricts approval/rejection to Super Admin and Accountant.
    If Accountant approves first: transitions claim to 'approved_by_accountant' (pending Super Admin).
    If Super Admin approves (either directly or after Accountant): transitions claim to 'approved'.
    Sends WhatsApp confirmation to the approver and status update to the claimant upon completion.
    """
    action, reimb_id = parse_reimbursement_payload(payload_str, text_str)
    if not action or not reimb_id:
        return False

    from .models import Reimbursement
    from django.contrib.auth import get_user_model
    from chat.notifications import send_whatsapp_text, send_system_notification
    from core.utils import get_role_filter_q

    try:
        reimb = Reimbursement.objects.select_related('user', 'branch', 'accountant_approved_by').get(id=reimb_id)
    except (Reimbursement.DoesNotExist, ValueError, TypeError):
        logger.warning("[WA REIMB] Reimbursement id=%s not found.", reimb_id)
        send_whatsapp_text(to=sender_wa_id, body="Reimbursement claim not found.")
        return True

    applicant_name = getattr(reimb.user, 'name', None) or getattr(reimb.user, 'email', 'Employee')

    if reimb.is_paid:
        send_whatsapp_text(
            to=sender_wa_id,
            body=f"This reimbursement claim '{reimb.title}' has already been marked as paid."
        )
        return True

    # Resolve approver user by sender phone number.
    User = get_user_model()
    phone_clean = str(sender_wa_id or '').strip()
    if phone_clean.startswith('+'):
        phone_clean = phone_clean[1:]
    phone_10 = phone_clean[2:] if (phone_clean.startswith('91') and len(phone_clean) == 12) else phone_clean

    phone_filter = (
        Q(phone=sender_wa_id) |
        Q(phone=phone_clean) |
        Q(phone=phone_10) |
        Q(phone=f'+91{phone_10}') |
        Q(phone=f'91{phone_10}') |
        Q(phone=f'+{phone_clean}')
    )
    if len(phone_10) == 10:
        phone_filter |= Q(phone__endswith=phone_10)

    candidates = list(User.objects.filter(phone_filter, is_active=True))

    if not candidates:
        logger.warning("[WA REIMB] No active user found for sender_wa_id=%s", sender_wa_id)
        send_whatsapp_text(
            to=sender_wa_id,
            body="Unauthorized: Your phone number is not registered as an authorized approver."
        )
        return True

    # Filter out claimant if other candidates exist with the same phone
    eligible_candidates = [u for u in candidates if u.id != reimb.user_id] or candidates

    approver = None
    # Super Admin takes precedence if candidate has both roles
    for u in eligible_candidates:
        if is_super_admin_user(u):
            approver = u
            break
    if not approver:
        for u in eligible_candidates:
            if is_accountant_user(u):
                approver = u
                break

    if not approver:
        for u in candidates:
            if is_super_admin_user(u):
                approver = u
                break
        if not approver:
            for u in candidates:
                if is_accountant_user(u):
                    approver = u
                    break

    if not approver:
        approver = eligible_candidates[0]

    if reimb.user == approver:
        send_whatsapp_text(
            to=sender_wa_id,
            body="You cannot approve or reject your own reimbursement claim."
        )
        return True

    user_is_sa = is_super_admin_user(approver)
    user_is_acc = is_accountant_user(approver)

    if not (user_is_sa or user_is_acc):
        send_whatsapp_text(
            to=sender_wa_id,
            body="Permission denied: Only Super Admin and Accountant are authorized to review reimbursement claims."
        )
        return True

    now = timezone.now()
    approver_name = getattr(approver, 'name', None) or getattr(approver, 'email', None) or 'Admin'

    # ── Action: REJECT ──────────────────────────────────────────────
    if action == 'reject':
        if reimb.status == 'approved':
            send_whatsapp_text(
                to=sender_wa_id,
                body=f"This reimbursement claim '{reimb.title}' for {applicant_name} has already been approved."
            )
            return True

        if reimb.status == 'rejected':
            send_whatsapp_text(
                to=sender_wa_id,
                body=f"This reimbursement claim '{reimb.title}' for {applicant_name} has already been rejected."
            )
            return True

        if reimb.status == 'approved_by_accountant' and not user_is_sa:
            send_whatsapp_text(
                to=sender_wa_id,
                body=f"This claim has already been approved by Accountant and is awaiting Super Admin final approval. Only Super Admin can reject it."
            )
            return True

        reimb.status = 'rejected'
        reimb.rejected_by = approver
        reimb.rejected_at = now
        reimb.rejection_reason = f"Rejected via WhatsApp by {approver_name}"
        reimb.approved_by = None
        reimb.approved_at = None
        reimb.save()

        send_whatsapp_text(
            to=sender_wa_id,
            body=f"❌ You have REJECTED the reimbursement claim '{reimb.title}' (₹{reimb.amount}) for {applicant_name}."
        )

        try:
            send_system_notification(
                user_id=str(reimb.user.id),
                title='Reimbursement Rejected',
                body=f"Your reimbursement claim '{reimb.title}' for ₹{reimb.amount} was rejected by {approver_name}.",
                metadata={
                    'reimbursement_id': str(reimb.id),
                    'type': 'reimbursement_rejected',
                    'status': 'rejected',
                    'route': f"/reimbursements/{reimb.id}",
                    'skip_whatsapp': True,
                },
                notification_type='payroll',
            )
        except Exception as e:
            logger.error("[WA REIMB] Failed notifying applicant of rejection: %s", e)

        # Notify claimant via WhatsApp
        try:
            send_reimbursement_status_whatsapp_to_applicant(reimb, 'rejected', reviewer_name=approver_name)
        except Exception as e:
            logger.error("[WA REIMB] Failed sending status WhatsApp to applicant: %s", e)

        return True

    # ── Action: APPROVE ─────────────────────────────────────────────
    if action == 'approve':
        if reimb.status == 'approved':
            send_whatsapp_text(
                to=sender_wa_id,
                body=f"This reimbursement claim '{reimb.title}' for {applicant_name} has already been approved."
            )
            return True

        if reimb.status == 'rejected':
            send_whatsapp_text(
                to=sender_wa_id,
                body=f"This reimbursement claim '{reimb.title}' for {applicant_name} has already been rejected."
            )
            return True

        if user_is_sa:
            # Super Admin approves directly from 'pending' OR completes Level 2 from 'approved_by_accountant'
            reimb.status = 'approved'
            reimb.approved_by = approver
            reimb.approved_at = now
            reimb.rejected_by = None
            reimb.rejected_at = None
            reimb.rejection_reason = ''
            reimb.save()

            send_whatsapp_text(
                to=sender_wa_id,
                body=f"✅ You have APPROVED the reimbursement claim '{reimb.title}' (₹{reimb.amount}) for {applicant_name}. Amount will be credited in monthly payroll."
            )

            try:
                send_system_notification(
                    user_id=str(reimb.user.id),
                    title='Reimbursement Approved',
                    body=f"Your reimbursement claim '{reimb.title}' for ₹{reimb.amount} has been approved by {approver_name} and will be added to your monthly pay.",
                    metadata={
                        'reimbursement_id': str(reimb.id),
                        'type': 'reimbursement_approved',
                        'status': 'approved',
                        'route': f"/reimbursements/{reimb.id}",
                        'skip_whatsapp': True,
                    },
                    notification_type='payroll',
                )
            except Exception as e:
                logger.error("[WA REIMB] Failed notifying applicant of approval: %s", e)

            # Notify claimant via WhatsApp
            try:
                send_reimbursement_status_whatsapp_to_applicant(reimb, 'approved', reviewer_name=approver_name)
            except Exception as e:
                logger.error("[WA REIMB] Failed sending status WhatsApp to applicant: %s", e)

            return True

        elif user_is_acc:
            # Accountant approving
            if reimb.status == 'approved_by_accountant':
                send_whatsapp_text(
                    to=sender_wa_id,
                    body=f"This reimbursement claim '{reimb.title}' has already been approved by Accountant and is awaiting final approval from Super Admin."
                )
                return True

            # Level 1 approval: move to approved_by_accountant
            reimb.status = 'approved_by_accountant'
            reimb.accountant_approved_by = approver
            reimb.accountant_approved_at = now
            reimb.rejected_by = None
            reimb.rejected_at = None
            reimb.rejection_reason = ''
            reimb.save()

            send_whatsapp_text(
                to=sender_wa_id,
                body=f"✅ You have approved the reimbursement claim '{reimb.title}' (₹{reimb.amount}) for {applicant_name}. It is now pending final approval from Super Admin."
            )

            try:
                send_system_notification(
                    user_id=str(reimb.user.id),
                    title='Reimbursement Claim Verified by Accountant',
                    body=f"Your reimbursement claim '{reimb.title}' for ₹{reimb.amount} has been approved by Accountant ({approver_name}) and is pending final approval from Super Admin.",
                    metadata={
                        'reimbursement_id': str(reimb.id),
                        'type': 'reimbursement_accountant_approved',
                        'status': 'approved_by_accountant',
                        'route': f"/reimbursements/{reimb.id}",
                        'skip_whatsapp': True,
                    },
                    notification_type='payroll',
                )
            except Exception as e:
                logger.error("[WA REIMB] Failed notifying applicant of accountant approval: %s", e)

            # Notify Super Admins for Level 2 final approval
            try:
                super_admins = list(User.objects.filter(get_role_filter_q(['super_admin']), is_active=True).distinct())
                for sa in super_admins:
                    if sa.id == reimb.user_id:
                        continue
                    send_system_notification(
                        user_id=str(sa.id),
                        title='Reimbursement Pending Final Approval',
                        body=f"Reimbursement claim '{reimb.title}' for ₹{reimb.amount} ({applicant_name}) was approved by Accountant ({approver_name}) and requires your final approval.",
                        metadata={
                            'reimbursement_id': str(reimb.id),
                            'type': 'reimbursement_claim',
                            'status': 'approved_by_accountant',
                            'route': f"/reimbursements/{reimb.id}",
                            'proof_url': get_reimbursement_proof_url(reimb),
                            'skip_whatsapp': True,
                        },
                        notification_type='payroll',
                    )
                    try:
                        send_reimbursement_whatsapp_notification(
                            reimb,
                            sa,
                            note_prefix=f"[Verified by Accountant: {approver_name}]"
                        )
                    except Exception as wa_err:
                        logger.error("[WA REIMB] WhatsApp to super_admin %s failed: %s", sa.id, wa_err)
            except Exception as e:
                logger.error("[WA REIMB] Failed notifying super admins of accountant approval: %s", e)

            return True

    return False

