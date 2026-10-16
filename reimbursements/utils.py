import logging
from django.utils import timezone
from django.db.models import Q

logger = logging.getLogger(__name__)


def send_reimbursement_whatsapp_notification(reimbursement, approver):
    """
    Sends WhatsApp notification with template quick-reply buttons (Approve / Reject)
    using the approved Meta template 'reimbursement_claim_' to an authorized approver.
    """
    if not approver or not getattr(approver, 'phone', None):
        return

    from chat.notifications import send_whatsapp_with_fallback

    applicant_name = getattr(reimbursement.user, 'name', None) or getattr(reimbursement.user, 'email', 'Staff Member')
    title_text = str(reimbursement.title or 'Expense Claim')[:100]
    amount_str = f"{reimbursement.amount:.2f}" if reimbursement.amount is not None else "0.00"
    expense_date_str = str(reimbursement.expense_date or timezone.now().date())
    description_text = (reimbursement.description or 'No description provided')[:100]

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


def parse_reimbursement_payload(payload_str, text_str=""):
    """
    Parses payload string (and optional text) to extract reimbursement action and UUID.
    Returns (action, reimbursement_id) or (None, None).
    """
    if not payload_str and not text_str:
        return None, None

    s = str(payload_str or "").strip()
    t = str(text_str or "").strip().lower()

    action = None
    reimb_id = None

    if s.startswith("reimb_approve:"):
        action = "approve"
        reimb_id = s[len("reimb_approve:"):]
    elif s.startswith("reimb_reject:"):
        action = "reject"
        reimb_id = s[len("reimb_reject:"):]
    elif s.startswith("reimb_approve_"):
        action = "approve"
        reimb_id = s[len("reimb_approve_"):]
    elif s.startswith("reimb_reject_"):
        action = "reject"
        reimb_id = s[len("reimb_reject_"):]
    elif s.startswith("reimbursement_approve:"):
        action = "approve"
        reimb_id = s[len("reimbursement_approve:"):]
    elif s.startswith("reimbursement_reject:"):
        action = "reject"
        reimb_id = s[len("reimbursement_reject:"):]
    elif ":" in s and ("reimb" in s or "reimbursement" in s):
        parts = s.split(":")
        if len(parts) >= 2:
            if "approve" in parts[0]:
                action = "approve"
                reimb_id = parts[-1]
            elif "reject" in parts[0]:
                action = "reject"
                reimb_id = parts[-1]

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
    Handles staff/approver action (Approve or Reject) for a Reimbursement claim
    triggered via WhatsApp template Quick Reply buttons.
    Returns True if handled as a reimbursement action, False otherwise.
    """
    action, reimb_id = parse_reimbursement_payload(payload_str, text_str)
    if not action or not reimb_id:
        return False

    from .models import Reimbursement
    from django.contrib.auth import get_user_model
    from chat.notifications import send_whatsapp_text, send_system_notification
    from core.utils import get_user_role, has_user_branch_access

    try:
        reimb = Reimbursement.objects.select_related('user', 'branch').get(id=reimb_id)
    except (Reimbursement.DoesNotExist, ValueError, TypeError):
        logger.warning("[WA REIMB] Reimbursement id=%s not found.", reimb_id)
        send_whatsapp_text(to=sender_wa_id, body="Reimbursement claim not found.")
        return True

    applicant_name = getattr(reimb.user, 'name', 'Employee')

    # Status check
    if reimb.status != 'pending':
        status_disp = getattr(reimb, 'get_status_display', lambda: reimb.status)()
        send_whatsapp_text(
            to=sender_wa_id,
            body=f"This reimbursement claim '{reimb.title}' for {applicant_name} has already been {status_disp.lower()}."
        )
        return True

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
        logger.warning("[WA REIMB] No active user found for sender_wa_id=%s", sender_wa_id)
        send_whatsapp_text(
            to=sender_wa_id,
            body="Unauthorized: Your phone number is not registered as an authorized approver."
        )
        return True

    # Filter out claimant if other candidates exist with the same phone
    eligible_candidates = [u for u in candidates if u.id != reimb.user_id] or candidates

    from .views import GLOBAL_ADMIN_ROLES, BRANCH_APPROVER_ROLES

    def is_user_approver(u):
        u_role = get_user_role(u)
        if any(u_role == r for r in GLOBAL_ADMIN_ROLES):
            return True
        if any(u_role == r for r in BRANCH_APPROVER_ROLES):
            if reimb.branch_id and has_user_branch_access(u, reimb.branch_id):
                return True
        return False

    approver = None
    for u in eligible_candidates:
        if is_user_approver(u):
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

    if not is_user_approver(approver):
        send_whatsapp_text(
            to=sender_wa_id,
            body="Permission denied: You are not authorized to review this reimbursement claim."
        )
        return True

    now = timezone.now()

    # ── Action: REJECT ──────────────────────────────────────────────
    if action == 'reject':
        reimb.status = 'rejected'
        reimb.rejected_by = approver
        reimb.rejected_at = now
        reimb.rejection_reason = f"Rejected via WhatsApp by {approver.name}"
        reimb.approved_by = None
        reimb.approved_at = None
        reimb.save(update_fields=['status', 'rejected_by', 'rejected_at', 'rejection_reason', 'approved_by', 'approved_at'])

        send_whatsapp_text(
            to=sender_wa_id,
            body=f"❌ You have REJECTED the reimbursement claim '{reimb.title}' (₹{reimb.amount}) for {applicant_name}."
        )

        try:
            send_system_notification(
                user_id=str(reimb.user.id),
                title='Reimbursement Rejected',
                body=f"Your reimbursement claim '{reimb.title}' for ₹{reimb.amount} was rejected by {approver.name}.",
                metadata={'reimbursement_id': str(reimb.id), 'type': 'reimbursement_rejected', 'status': 'rejected'},
                notification_type='payroll',
            )
        except Exception as e:
            logger.error("[WA REIMB] Failed notifying applicant of rejection: %s", e)

        return True

    # ── Action: APPROVE ─────────────────────────────────────────────
    if action == 'approve':
        reimb.status = 'approved'
        reimb.approved_by = approver
        reimb.approved_at = now
        reimb.rejected_by = None
        reimb.rejected_at = None
        reimb.rejection_reason = ''
        reimb.save(update_fields=['status', 'approved_by', 'approved_at', 'rejected_by', 'rejected_at', 'rejection_reason'])

        send_whatsapp_text(
            to=sender_wa_id,
            body=f"✅ You have APPROVED the reimbursement claim '{reimb.title}' (₹{reimb.amount}) for {applicant_name}. Amount will be credited in monthly payroll."
        )

        try:
            send_system_notification(
                user_id=str(reimb.user.id),
                title='Reimbursement Approved',
                body=f"Your reimbursement claim '{reimb.title}' for ₹{reimb.amount} has been approved by {approver.name} and will be added to your monthly pay.",
                metadata={'reimbursement_id': str(reimb.id), 'type': 'reimbursement_approved', 'status': 'approved'},
                notification_type='payroll',
            )
        except Exception as e:
            logger.error("[WA REIMB] Failed notifying applicant of approval: %s", e)

        return True

    return False
