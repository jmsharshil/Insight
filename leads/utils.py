import logging

from django.db import transaction

from .models import Lead, LeadStage, LeadAssignmentLog, STAGE_NEW


logger = logging.getLogger(__name__)


class LeadService:

    @staticmethod
    @transaction.atomic
    def create_lead(validated_data: dict, user=None) -> Lead:
        """
        Creates a Lead + initial LeadStage from validated serializer data.

        - Called from view after serializer.is_valid()
        - user = None means system created (form submission)
        - transaction.atomic ensures if anything fails, nothing saves

        Args:
            validated_data : dict  — from serializer.validated_data
            user           : User  — pass request.user if staff creates manually from CRM

        Returns:
            Lead instance
        """

        try:
            # ── Step 1: Extract document files separately ─────────────────────
            # Files can't go into Lead.objects.create() directly with other fields
            # We save the lead first, then attach files (because upload path needs lead.id)

            doc_fields = {
                key: validated_data.pop(key)
                for key in list(validated_data.keys())
                if key.startswith('doc_')
            }

            # ── Step 2: Remove form_type from data — already in validated_data ─
            # Set initial stage based on form type
            form_type = validated_data.get('form_type')
            initial_stage = 'interested' if form_type == 'inquiry' else STAGE_NEW
            validated_data['current_stage'] = initial_stage

            # ── Step 2b: Extract assigned_to before creating the Lead ──────────
            # It is already resolved to a User instance (or None) by the serializer.
            # Only honour it when a real user initiated the request (not a public form).
            assigned_to_user = validated_data.pop('assigned_to', None)
            if user is not None and assigned_to_user is not None:
                # Store on the lead (field exists on model)
                validated_data['assigned_to'] = assigned_to_user
            # If user is None (public form submission) we silently ignore assigned_to.

            # ── Step 3: Create the Lead ───────────────────────────────────────
            lead = Lead.objects.create(**validated_data)

            # ── Step 4: Attach documents if any (registration form) ───────────
            if doc_fields:
                LeadService._attach_documents(lead, doc_fields)

            # ── Step 5: Create initial stage history entry ────────────────────
            LeadStage.objects.create(
                lead=lead,
                stage=initial_stage,
                changed_by=user,        # None = form submission, User = staff manual entry
                note=f"Lead created via {lead.form_type} form."
            )

            # ── Step 6: Log initial assignment if one was set at creation ───────
            if lead.assigned_to is not None:
                LeadAssignmentLog.objects.create(
                    lead=lead,
                    assigned_from=None,
                    assigned_to=lead.assigned_to,
                    changed_by=user,
                    note=f"Initial assignment at lead creation by {user}."
                )
                logger.info(
                    f"Lead {lead.id} assigned to {lead.assigned_to} at creation."
                )

            logger.info(f"Lead created successfully — ID: {lead.id} | Form: {lead.form_type}")

            return lead

        except Exception as e:
            # transaction.atomic rolls back everything above automatically
            logger.error(f"Lead creation failed — {str(e)} | Data: {validated_data}")
            raise

    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def update_stage(lead_id: int, new_stage: str, user, note: str = '') -> Lead:
        """
        Moves a lead to a new stage.
        Called from CRM when staff updates lead status.

        Args:
            lead_id   : int    — Lead primary key
            new_stage : str    — must be a valid Lead.StageType choice
            user      : User   — staff member making the change (required)
            note      : str    — optional note about why stage changed

        Returns:
            Updated Lead instance
        """

        try:
            lead = Lead.objects.get(id=lead_id)
        except Lead.DoesNotExist:
            logger.warning(f"Stage update failed — Lead ID {lead_id} not found.")
            raise

        old_stage = lead.current_stage

        if old_stage == new_stage:
            # No change — don't create duplicate history entry
            return lead

        with transaction.atomic():
            lead.current_stage = new_stage
            lead.save(update_fields=['current_stage', 'updated_at'])

            LeadStage.objects.create(
                lead=lead,
                stage=new_stage,
                changed_by=user,
                note=note or f"Stage changed from {old_stage} to {new_stage}."
            )

        logger.info(
            f"Lead ID {lead.id} stage updated — "
            f"{old_stage} → {new_stage} by {user}"
        )

        return lead

    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _attach_documents(lead: Lead, doc_fields: dict) -> None:
        """
        Saves document files to the lead instance.
        Called internally after lead is created (needs lead.id for file path).

        Args:
            lead       : Lead  — already saved Lead instance
            doc_fields : dict  — {'doc_signature': <file>, 'doc_photo': <file>, ...}
        """

        for field_name, file in doc_fields.items():
            if file:
                setattr(lead, field_name, file)

        lead.save(update_fields=list(doc_fields.keys()))


# ═══════════════════════════════════════════════════════════════════════════════
# Sales Attendance Approval Workflow & WhatsApp Integration
# ═══════════════════════════════════════════════════════════════════════════════

def get_sales_attendance_approvers(sales_user):
    """
    Returns users who are CMO or Super Admin in the user's organization.
    Both CMO and Super Admin are authorized to approve sales attendance selfies.
    """
    from django.contrib.auth import get_user_model
    from django.db.models import Q
    User = get_user_model()
    org = getattr(sales_user, 'organization', None)

    qs = User.objects.filter(is_active=True)
    if org:
        qs = qs.filter(Q(organization=org) | Q(organization__isnull=True))

    approvers = []
    seen_ids = set()
    for u in qs:
        if u.id == sales_user.id or u.id in seen_ids:
            continue
        roles = [u.role] + (getattr(u, 'additional_roles', None) or [])
        if 'cmo' in roles or 'super_admin' in roles or getattr(u, 'is_superuser', False):
            approvers.append(u)
            seen_ids.add(u.id)

    return approvers


def get_sales_attendance_super_admins(sales_user):
    """
    Returns users who are Super Admin in the user's organization.
    """
    from django.contrib.auth import get_user_model
    from django.db.models import Q
    User = get_user_model()
    org = getattr(sales_user, 'organization', None)

    qs = User.objects.filter(is_active=True)
    if org:
        qs = qs.filter(Q(organization=org) | Q(organization__isnull=True))

    super_admins = []
    seen_ids = set()
    for u in qs:
        if u.id == sales_user.id or u.id in seen_ids:
            continue
        roles = [u.role] + (getattr(u, 'additional_roles', None) or [])
        if 'super_admin' in roles or getattr(u, 'is_superuser', False):
            super_admins.append(u)
            seen_ids.add(u.id)

    return super_admins


def send_sales_attendance_whatsapp_notification(approval, approver, is_step2=False):
    """
    Sends WhatsApp notification with template quick-reply buttons (Approve / Reject)
    to CMO or Super Admin for a sales person's start_selfie or end_selfie attendance.
    Includes the uploaded selfie photo link for approver verification.
    If is_step2=True, informs Super Admin that CMO has already verified the request.
    """
    if not approver or not getattr(approver, 'phone', None):
        return

    import os
    from django.conf import settings
    from django.utils import timezone
    from chat.notifications import send_whatsapp_with_fallback

    applicant_name = " ".join(str(getattr(approval.user, 'name', None) or approval.user.email).split())[:60]
    approval_type_display = approval.get_approval_type_display()  # "Check In" or "Check Out"
    date_str = str(approval.date)
    time_str = timezone.localtime(approval.captured_at).strftime("%I:%M %p") if approval.captured_at else ""
    
    loc_parts = []
    if approval.latitude and approval.longitude:
        loc_parts.append(f"GPS: {approval.latitude}, {approval.longitude}")
    if getattr(approval.activity, 'name', None) and approval.activity.name != "Daily Field Operations":
        loc_parts.append(approval.activity.name)
    loc_str = " ".join(" | ".join(loc_parts).split())[:60] if loc_parts else "Field selfie GPS logged"

    # Resolve selfie photo URL
    photo_url = ""
    try:
        photo_field = getattr(approval.photo, 'photo', None) if getattr(approval, 'photo', None) else None
        if photo_field and hasattr(photo_field, 'url'):
            raw_url = photo_field.url
            if raw_url.startswith("http://") or raw_url.startswith("https://"):
                photo_url = raw_url
            else:
                base_url = (
                    getattr(settings, 'BACKEND_URL', None) or
                    getattr(settings, 'SITE_URL', None) or
                    getattr(settings, 'BASE_URL', None) or
                    os.environ.get('BACKEND_URL', '') or
                    os.environ.get('SITE_URL', '')
                )
                if not base_url:
                    for h in getattr(settings, 'ALLOWED_HOSTS', []):
                        if h and h not in ('*', '127.0.0.1', 'localhost') and not h.startswith('.'):
                            base_url = f"https://{h}"
                            break
                photo_url = f"{base_url.rstrip('/')}{raw_url}" if base_url else raw_url
    except Exception as e:
        logger.warning("[WA SALES ATT] Failed resolving photo URL: %s", e)
        photo_url = ""

    photo_display = photo_url or "No photo uploaded"

    if is_step2:
        cmo_name = getattr(approval.cmo_approved_by, 'name', None) or 'CMO'
        req_type_text = f"Sales {approval_type_display} (CMO Approved)"
        notif_body = (
            f"Sales Attendance Final Approval Request:\n"
            f"Salesperson: {applicant_name}\n"
            f"Request: {approval_type_display} (Verified by CMO {cmo_name})\n"
            f"Date & Time: {date_str} {time_str}\n"
            f"Location: {loc_str}\n"
            f"Selfie Photo: {photo_display}\n\n"
            f"Reply 'sales_att_approve:{approval.id}' to Approve or 'sales_att_reject:{approval.id}' to Reject."
        )
    else:
        req_type_text = f"Sales {approval_type_display}"
        notif_body = (
            f"Sales Attendance Approval Request:\n"
            f"Salesperson: {applicant_name}\n"
            f"Request: {approval_type_display}\n"
            f"Date & Time: {date_str} {time_str}\n"
            f"Location: {loc_str}\n"
            f"Selfie Photo: {photo_display}\n\n"
            f"Reply 'sales_att_approve:{approval.id}' to Approve or 'sales_att_reject:{approval.id}' to Reject."
        )

    template_name = getattr(
        settings,
        'WHATSAPP_SALES_ATTENDANCE_APPROVAL_TEMPLATE',
        os.environ.get('WHATSAPP_SALES_ATTENDANCE_APPROVAL_TEMPLATE', 'sales_attendance_approval_')
    )

    header_img_url = photo_url or (
        "https://insightinstitute-fufvf3dbe0grg2b3.centralindia-01.azurewebsites.net/static/images/payment_receipt_placeholder.png"
    )

    components = [
        {
            "type": "header",
            "parameters": [
                {
                    "type": "image",
                    "image": {"link": header_img_url}
                }
            ]
        },
        {
            "type": "body",
            "parameters": [
                {"type": "text", "text": str(applicant_name)},
                {"type": "text", "text": str(req_type_text)},
                {"type": "text", "text": str(date_str)},
                {"type": "text", "text": str(time_str)},
                {"type": "text", "text": str(loc_str)},
            ]
        },
        {
            "type": "button",
            "sub_type": "quick_reply",
            "index": "0",
            "parameters": [{"type": "payload", "payload": f"sales_att_approve:{approval.id}"}]
        },
        {
            "type": "button",
            "sub_type": "quick_reply",
            "index": "1",
            "parameters": [{"type": "payload", "payload": f"sales_att_reject:{approval.id}"}]
        }
    ]

    try:
        send_whatsapp_with_fallback(
            to=approver.phone,
            template_name=template_name,
            language_code="en",
            components=components,
            fallback_body=notif_body,
            user_id=str(approver.id),
        )
        logger.info("[WA SALES ATT] Sent approval notification (%s) for %s to %s (%s)", template_name, approval.id, approver.name, approver.phone)
    except Exception as e:
        logger.error("[WA SALES ATT] Failed sending approval notification for %s to %s: %s", approval.id, approver.id, e)


def send_sales_attendance_approval_requests(approval):
    """
    Sends WhatsApp and in-app system notifications to both CMO and Super Admin.
    """
    from chat.notifications import send_system_notification
    approvers = get_sales_attendance_approvers(approval.user)
    if not approvers:
        logger.warning("[SALES ATT] No CMO or Super Admin approvers found for user %s", approval.user.id)
        return

    applicant_name = getattr(approval.user, 'name', 'Sales Employee')
    approval_type_display = approval.get_approval_type_display()

    for approver in approvers:
        # WhatsApp notification
        send_sales_attendance_whatsapp_notification(approval, approver)

        # In-app notification
        try:
            send_system_notification(
                user_id=str(approver.id),
                title=f"Sales Attendance Approval Request: {applicant_name}",
                body=f"{applicant_name} submitted {approval_type_display} with selfie on {approval.date}. Please review and approve.",
                metadata={"approval_id": str(approval.id), "type": "sales_attendance_approval"}
            )
        except Exception as e:
            logger.error("[SALES ATT] In-app notification to %s failed: %s", approver.id, e)


def send_sales_attendance_cmo_approved_to_super_admins(approval):
    """
    Called when CMO approves at Step 1.
    Sends WhatsApp and in-app system notifications to Super Admin(s)
    alerting them that CMO has verified/approved and final approval is required.
    """
    from chat.notifications import send_system_notification
    super_admins = get_sales_attendance_super_admins(approval.user)
    if not super_admins:
        logger.warning("[SALES ATT] No Super Admin found for user %s to receive final approval", approval.user.id)
        return

    applicant_name = getattr(approval.user, 'name', 'Sales Employee')
    approval_type_display = approval.get_approval_type_display()
    cmo_name = getattr(approval.cmo_approved_by, 'name', 'CMO')

    for sa in super_admins:
        # WhatsApp notification with is_step2=True
        send_sales_attendance_whatsapp_notification(approval, sa, is_step2=True)

        # In-app notification
        try:
            send_system_notification(
                user_id=str(sa.id),
                title=f"Final Approval Needed: Sales Attendance for {applicant_name}",
                body=f"CMO {cmo_name} has approved {approval_type_display} for {applicant_name} on {approval.date}. Your final approval is required to finalize attendance.",
                metadata={
                    "approval_id": str(approval.id),
                    "type": "sales_attendance_approval",
                    "step": "super_admin_final"
                }
            )
        except Exception as e:
            logger.error("[SALES ATT] In-app notification to Super Admin %s failed: %s", sa.id, e)


def apply_sales_attendance_approval(approval, approver):
    """
    Applies approval for sales attendance:
    - If approver is CMO (and not Super Admin):
      - If status == 'pending': Moves status to 'cmo_approved', records cmo_approved_by & cmo_approved_at,
        and alerts Super Admin that final approval is needed. Attendance record is NOT created yet.
      - If status == 'cmo_approved': Returns already approved by CMO.
    - If approver is Super Admin:
      - Can approve from 'pending' (direct approve) or from 'cmo_approved' (final approve).
      - Marks status as 'approved', creates/updates EmployeeAttendanceRecord, and notifies salesperson.
    """
    from django.utils import timezone
    from attendance.models import EmployeeAttendanceRecord
    from core.utils import get_user_branch_id
    from branch.models import Branch
    from chat.notifications import send_whatsapp_text, send_system_notification

    if approval.status == 'approved':
        return False, "This request has already been approved."
    if approval.status == 'rejected':
        return False, "This request has already been rejected."

    roles = [approver.role] + (getattr(approver, 'additional_roles', None) or [])
    user_is_sa = 'super_admin' in roles or getattr(approver, 'is_superuser', False)
    user_is_cmo = 'cmo' in roles

    if not user_is_sa and not user_is_cmo:
        return False, "Permission denied: Only CMO or Super Admin can approve sales attendance."

    now = timezone.now()
    applicant_name = getattr(approval.user, 'name', 'Employee')
    approval_type_disp = approval.get_approval_type_display()

    # ── CASE 1: CMO Approval (Step 1) ──────────────────────────────────────────
    if user_is_cmo and not user_is_sa:
        if approval.status == 'cmo_approved':
            return False, "This request has already been approved by CMO and is awaiting final Super Admin approval."

        approval.status = 'cmo_approved'
        approval.cmo_approved_by = approver
        approval.cmo_approved_at = now
        approval.save(update_fields=['status', 'cmo_approved_by', 'cmo_approved_at', 'updated_at'])

        # Notify Super Admins for final approval
        send_sales_attendance_cmo_approved_to_super_admins(approval)

        # Notify applicant that CMO has verified
        try:
            send_system_notification(
                user_id=str(approval.user.id),
                title=f"Attendance {approval_type_disp} Verified by CMO",
                body=f"Your sales {approval_type_disp.lower()} on {approval.date} has been verified by CMO {approver.name} and forwarded to Super Admin for final approval.",
                metadata={"approval_id": str(approval.id), "status": "cmo_approved"}
            )
        except Exception as e:
            logger.error("[SALES ATT] In-app notification to applicant failed: %s", e)

        return True, "First approval completed by CMO. Awaiting Super Admin final approval."

    # ── CASE 2: Super Admin Direct / Final Approval ────────────────────────────
    approval.status = 'approved'
    approval.approved_by = approver
    approval.approved_at = now

    bid = get_user_branch_id(approval.user) or getattr(approval.user, 'branch_id', None)
    if not bid:
        first_branch = Branch.objects.filter(organization=approval.user.organization).first() or Branch.objects.first()
        bid = first_branch.id if first_branch else None

    # Clear stale absent record
    EmployeeAttendanceRecord.objects.filter(
        user=approval.user, date=approval.date, status='absent'
    ).delete()

    if approval.approval_type == 'check_in':
        rec, _ = EmployeeAttendanceRecord.objects.update_or_create(
            user=approval.user,
            date=approval.date,
            defaults={
                'branch_id': bid,
                'status': 'checkout_pending',
                'checked_in_at': approval.captured_at,
                'latitude': approval.latitude,
                'longitude': approval.longitude,
                'location_verified': False,
                'marked_by': approver,
                'check_in_method': 'selfie',
            }
        )
        approval.attendance_record = rec
        approval.save()

    elif approval.approval_type == 'check_out':
        open_rec = EmployeeAttendanceRecord.objects.filter(
            user=approval.user,
            date=approval.date,
            checked_in_at__isnull=False,
        ).order_by('-checked_in_at').first()

        if open_rec:
            open_rec.checked_out_at = approval.captured_at
            open_rec.status = 'present'
            open_rec.check_out_method = 'selfie'

            role = getattr(approval.user, 'role', '')
            if role not in {'faculty', 'sweeper', 'maid', 'driver'} and open_rec.checked_in_at:
                from decimal import Decimal
                checkout_time = approval.captured_at
                duration_mins = int((checkout_time - open_rec.checked_in_at).total_seconds() / 60)
                req_mins = 540
                target_dt = getattr(open_rec, 'date', None) or checkout_time.date()
                has_half_day_leave = False
                try:
                    from leave.models import LeaveApplication
                    if target_dt and hasattr(approval.user, 'id') and LeaveApplication.objects.filter(
                        applied_by=approval.user,
                        from_date__lte=target_dt,
                        to_date__gte=target_dt,
                        is_half_day=True,
                        status__in=['approved', 'approval_pending'],
                    ).exists():
                        req_mins = 300
                        has_half_day_leave = True
                except Exception:
                    pass

                if not has_half_day_leave:
                    if hasattr(approval.user, 'get_working_hours_for_date'):
                        dwh = approval.user.get_working_hours_for_date(target_dt)
                        if dwh > 0:
                            req_mins = int(Decimal(str(dwh)) * 60)
                    elif getattr(approval.user, 'working_hours', None) and approval.user.working_hours > 0:
                        req_mins = int(Decimal(str(approval.user.working_hours)) * 60)
                shortfall = max(0, req_mins - duration_mins)
                open_rec.shortfall_minutes = shortfall

            open_rec.save()
            from attendance.utils import apply_half_day_rule
            apply_half_day_rule(open_rec, approval.user, approval.captured_at)

            approval.attendance_record = open_rec
            approval.save()
        else:
            if bid:
                rec = EmployeeAttendanceRecord.objects.create(
                    user=approval.user,
                    branch_id=bid,
                    date=approval.date,
                    status='present',
                    checked_in_at=approval.captured_at,
                    checked_out_at=approval.captured_at,
                    latitude=approval.latitude,
                    longitude=approval.longitude,
                    location_verified=False,
                    marked_by=approver,
                    check_in_method='selfie',
                    check_out_method='selfie',
                )
                approval.attendance_record = rec
                approval.save()

    # Notify applicant of final approval
    if getattr(approval.user, 'phone', None):
        try:
            send_whatsapp_text(
                to=approval.user.phone,
                body=f"Hello {applicant_name}, your sales {approval_type_disp.lower()} on {approval.date} has been APPROVED by Super Admin {approver.name}. Your attendance entry has arrived."
            )
        except Exception as e:
            logger.error("[SALES ATT] WhatsApp to applicant %s failed: %s", approval.user.id, e)

    try:
        send_system_notification(
            user_id=str(approval.user.id),
            title=f"Attendance {approval_type_disp} Approved",
            body=f"Your sales {approval_type_disp.lower()} on {approval.date} has been approved by Super Admin {approver.name}.",
            metadata={"approval_id": str(approval.id), "status": "approved"}
        )
    except Exception as e:
        logger.error("[SALES ATT] In-app notification to applicant failed: %s", e)

    # If CMO had verified earlier, notify CMO that Super Admin completed final approval
    if approval.cmo_approved_by_id and approval.cmo_approved_by_id != approver.id:
        try:
            send_system_notification(
                user_id=str(approval.cmo_approved_by_id),
                title=f"Sales Attendance Approved by Super Admin: {applicant_name}",
                body=f"Super Admin {approver.name} has finalized approval for {applicant_name}'s {approval_type_disp.lower()} on {approval.date}.",
                metadata={"approval_id": str(approval.id), "status": "approved"}
            )
        except Exception as e:
            logger.error("[SALES ATT] Notification to CMO failed: %s", e)

    return True, f"Sales {approval.get_approval_type_display().lower()} approved successfully."


def apply_sales_attendance_rejection(approval, approver, reason=""):
    """
    Rejects the attendance request by CMO or Super Admin.
    """
    from django.utils import timezone
    from chat.notifications import send_whatsapp_text, send_system_notification

    if approval.status in ('approved', 'rejected'):
        return False, f"This request has already been {approval.get_status_display().lower()}."

    now = timezone.now()
    approval.status = 'rejected'
    approval.rejected_by = approver
    approval.rejected_at = now
    approval.rejection_reason = reason or f"Rejected by {approver.name}"
    approval.save()

    applicant_name = getattr(approval.user, 'name', 'Employee')
    approval_type_disp = approval.get_approval_type_display()

    # Notify applicant
    if getattr(approval.user, 'phone', None):
        try:
            send_whatsapp_text(
                to=approval.user.phone,
                body=f"Hello {applicant_name}, your sales {approval_type_disp.lower()} on {approval.date} was REJECTED by {approver.name}. Reason: {approval.rejection_reason}"
            )
        except Exception as e:
            logger.error("[SALES ATT] WhatsApp rejection to applicant %s failed: %s", approval.user.id, e)

    try:
        send_system_notification(
            user_id=str(approval.user.id),
            title=f"Attendance {approval_type_disp} Rejected",
            body=f"Your sales {approval_type_disp.lower()} on {approval.date} was rejected by {approver.name}.",
            metadata={"approval_id": str(approval.id), "status": "rejected"}
        )
    except Exception as e:
        logger.error("[SALES ATT] In-app rejection to applicant failed: %s", e)

    return True, f"Sales {approval.get_approval_type_display().lower()} rejected."


def parse_sales_attendance_payload(payload_str, text_str=""):
    """
    Parses payload string (and optional text) to extract sales attendance action and UUID.
    Returns (action, approval_id) or (None, None).
    """
    import uuid
    if not payload_str and not text_str:
        return None, None

    candidates = [str(payload_str or "").strip(), str(text_str or "").strip()]
    action = None
    approval_id = None

    for s in candidates:
        if not s:
            continue
        s_lower = s.lower()
        if s_lower.startswith("sales_att_approve:") or s_lower.startswith("sales_attendance_approve:"):
            action = "approve"
            approval_id = s.split(":", 1)[1].strip()
            break
        elif s_lower.startswith("sales_att_reject:") or s_lower.startswith("sales_attendance_reject:"):
            action = "reject"
            approval_id = s.split(":", 1)[1].strip()
            break
        elif s_lower.startswith("sales_att_approve_") or s_lower.startswith("sales_attendance_approve_"):
            action = "approve"
            approval_id = s.split("_")[-1].strip()
            break
        elif s_lower.startswith("sales_att_reject_") or s_lower.startswith("sales_attendance_reject_"):
            action = "reject"
            approval_id = s.split("_")[-1].strip()
            break
        elif s_lower.startswith("approve_sales_att_") or s_lower.startswith("approve_sales_"):
            action = "approve"
            approval_id = s.split("_")[-1].strip()
            break
        elif s_lower.startswith("reject_sales_att_") or s_lower.startswith("reject_sales_"):
            action = "reject"
            approval_id = s.split("_")[-1].strip()
            break
        elif s_lower.startswith("approve sales ") or s_lower.startswith("sales approve "):
            action = "approve"
            approval_id = s.split()[-1].strip()
            break
        elif s_lower.startswith("reject sales ") or s_lower.startswith("sales reject "):
            action = "reject"
            approval_id = s.split()[-1].strip()
            break

    # Validate UUID
    if approval_id:
        try:
            uuid_obj = uuid.UUID(approval_id)
            approval_id = str(uuid_obj)
        except (ValueError, TypeError):
            approval_id = None

    return action, approval_id


def handle_sales_attendance_whatsapp_approval(sender_wa_id, payload_str, text_str=""):
    """
    Handles CMO or Super Admin approval/rejection for sales attendance selfies
    via WhatsApp Quick Reply buttons or text replies.
    """
    action, approval_id = parse_sales_attendance_payload(payload_str, text_str)
    if not action or not approval_id:
        return False

    from django.contrib.auth import get_user_model
    from django.db.models import Q
    from chat.notifications import send_whatsapp_text
    from .models import SalesAttendanceApproval

    try:
        approval = SalesAttendanceApproval.objects.select_related('user', 'activity').get(id=approval_id)
    except (SalesAttendanceApproval.DoesNotExist, ValueError, TypeError):
        logger.warning("[WA SALES ATT] SalesAttendanceApproval id=%s not found.", approval_id)
        send_whatsapp_text(to=sender_wa_id, body="Sales attendance approval request not found.")
        return True

    applicant_name = getattr(approval.user, 'name', 'Sales Employee')
    approval_type_disp = approval.get_approval_type_display()

    if approval.status in ('approved', 'rejected'):
        status_disp = approval.get_status_display()
        send_whatsapp_text(
            to=sender_wa_id,
            body=f"This {approval_type_disp.lower()} request for {applicant_name} has already been {status_disp.lower()}."
        )
        return True

    # Resolve approver user by sender phone number
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
        logger.warning("[WA SALES ATT] No active user found for sender_wa_id=%s", sender_wa_id)
        send_whatsapp_text(
            to=sender_wa_id,
            body="Unauthorized: Your phone number is not registered as an authorized approver."
        )
        return True

    # Filter out applicant if they have the same phone
    eligible = [u for u in candidates if u.id != approval.user_id] or candidates

    def user_has_approver_role(u):
        if not u:
            return False
        roles = [u.role] + (getattr(u, 'additional_roles', None) or [])
        return 'cmo' in roles or 'super_admin' in roles or getattr(u, 'is_superuser', False)

    approver = next((u for u in eligible if user_has_approver_role(u)), None)
    if not approver:
        send_whatsapp_text(
            to=sender_wa_id,
            body="Permission denied: Only CMO or Super Admin can approve sales attendance."
        )
        return True

    if approval.user_id == approver.id:
        send_whatsapp_text(
            to=sender_wa_id,
            body="You cannot approve your own attendance request."
        )
        return True

    roles = [approver.role] + (getattr(approver, 'additional_roles', None) or [])
    user_is_sa = 'super_admin' in roles or getattr(approver, 'is_superuser', False)
    user_is_cmo = 'cmo' in roles

    if approval.status == 'cmo_approved' and user_is_cmo and not user_is_sa:
        send_whatsapp_text(
            to=sender_wa_id,
            body=f"This {approval_type_disp.lower()} request for {applicant_name} has already been approved by CMO and is awaiting final Super Admin approval."
        )
        return True

    if action == 'approve':
        success, msg = apply_sales_attendance_approval(approval, approver)
        if success:
            if approval.status == 'cmo_approved':
                send_whatsapp_text(
                    to=sender_wa_id,
                    body=f"✅ You have approved sales {approval_type_disp.lower()} for {applicant_name} (CMO Step 1). Request has been forwarded to Super Admin for final approval."
                )
            else:
                send_whatsapp_text(
                    to=sender_wa_id,
                    body=f"✅ You have APPROVED sales {approval_type_disp.lower()} for {applicant_name} ({approval.date}). Entry has arrived in attendance."
                )
        else:
            send_whatsapp_text(to=sender_wa_id, body=msg)
        return True

    elif action == 'reject':
        reason = f"Rejected via WhatsApp by {approver.name}"
        success, msg = apply_sales_attendance_rejection(approval, approver, reason=reason)
        if success:
            send_whatsapp_text(
                to=sender_wa_id,
                body=f"❌ You have REJECTED sales {approval_type_disp.lower()} for {applicant_name} ({approval.date})."
            )
        else:
            send_whatsapp_text(to=sender_wa_id, body=msg)
        return True

    return False