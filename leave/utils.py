import logging
from decimal import Decimal
from datetime import timedelta
from django.utils import timezone

logger = logging.getLogger(__name__)


# ── Stub notification helper ──────────────────────────────────────────────────

def notify(recipient_user_id, title, body, metadata=None, email_template=None, email_context=None, email_subject=None):
    from chat.notifications import send_system_notification
    if recipient_user_id:
        send_system_notification(
            user_id=str(recipient_user_id),
            title=title,
            body=body,
            metadata=metadata,
            email_template=email_template,
            email_context=email_context,
            email_subject=email_subject,
        )
def calculate_leave_days(from_date, to_date, is_half_day=False,
                         sandwich_rule=False, branch=None, user_role=None):
    """
    FRD §4.9.3 — Sandwich Leave + role rules (Sunday=1.5 for select roles, regular=1.0).
    - is_half_day: always 0.5
    - sandwich_rule=True: count *every* day (weekends + public holidays) as 1.0
    - sandwich_rule=False:
      * Public holidays: skipped
      * Sunday (weekday=6): 1.5 for branch_manager/admin_senior_executive/
        admin_executive/front_desk; 0 for others
      * All other days: 1.0
    - Uses timedelta for date iteration; returns Decimal.
    """
    if is_half_day:
        return Decimal('0.5')

    # Get public holiday dates for this branch in the date range
    public_holiday_dates = set()
    if branch:
        from .models import PublicHoliday
        from django.db import models
        holidays = PublicHoliday.objects.filter(
            models.Q(branch=branch) | models.Q(branch__organization=branch.organization_id),
            date__gte=from_date,
            date__lte=to_date,
        ).values_list('date', flat=True)
        public_holiday_dates = set(holidays)

    SPECIAL_SUNDAY_ROLES = {'branch_manager', 'admin_senior_executive',
                            'admin_executive', 'front_desk'}

    days = Decimal(0)
    current = from_date
    while current <= to_date:
        weekday = current.weekday()
        is_holiday = current in public_holiday_dates

        if is_holiday and not sandwich_rule:
            # Normal mode: skip public holidays
            pass
        elif weekday == 6 and user_role in SPECIAL_SUNDAY_ROLES:
            # Sunday is 1.5 for these roles, always (unless it was a free holiday, handled above)
            days += Decimal('1.5')
        elif weekday == 6 and not sandwich_rule:
            # Sunday is free for regular roles in normal mode
            pass
        else:
            # Regular working day, OR a holiday/weekend that is being sandwiched
            days += Decimal(1)

        current += timedelta(days=1)
    return days


def check_leave_overlap(user, from_date, to_date, exclude_id=None):
    """Check if user has overlapping approved leave."""
    from .models import LeaveApplication
    qs = LeaveApplication.objects.filter(
        applied_by=user,
        status='approved',
        from_date__lte=to_date,
        to_date__gte=from_date,
    )
    if exclude_id:
        qs = qs.exclude(id=exclude_id)
    conflict = qs.first()
    return (conflict is not None, conflict)


def initialize_leave_balances_for_year(branch, year):
    """Initialize leave balances for all active staff in a branch for the given year."""
    from .models import LeavePolicy, LeaveBalance
    from django.contrib.auth import get_user_model
    User = get_user_model()

    staff_roles = [
        'super_admin', 'faculty', 'branch_manager', 'admin_senior_executive', 'admin_executive',
        'front_desk', 'counsellor', 'sales_senior_executive', 'sales_executive',
        'tele_caller', 'exam_supervisor', 'paper_checker', 'accountant',
        # house_keeping/security have no leave option (special Sunday attendance rules instead)
    ]
    
    # Filter users to only those in the given branch (or if they are super_admin and want to test)
    from core.utils import get_user_branch_id
    all_staff = User.objects.filter(role__in=staff_roles, is_active=True)
    staff = []
    for u in all_staff:
        u_bid = get_user_branch_id(u)
        if str(u_bid) == str(branch.id) or u.role == 'super_admin':
            staff.append(u)
    policies = LeavePolicy.objects.filter(branch=branch, is_active=True)

    created_count = 0
    for user in staff:
        for policy in policies:
            carried = Decimal(0)
            if policy.carry_forward:
                prev = LeaveBalance.objects.filter(
                    user=user, leave_type=policy.leave_type, year=year - 1
                ).first()
                if prev:
                    remaining = prev.remaining_days
                    carried = min(remaining, Decimal(policy.max_carry_days))
                    carried = max(carried, Decimal(0))

            balance, was_created = LeaveBalance.objects.get_or_create(
                user=user, leave_type=policy.leave_type, year=year,
                defaults={
                    'total_days': Decimal(policy.annual_quota),
                    'carried_forward': carried,
                },
            )
            if was_created:
                created_count += 1
            else:
                # Update existing balance according to changed policy
                balance.total_days = Decimal(policy.annual_quota)
                balance.save(update_fields=['total_days'])

    logger.info(f"Initialized {created_count} leave balances for branch={branch.id}, year={year}")
    return created_count


def check_late_entry_threshold(user, month, year):
    """
    NEW (FRD §4.9.3): called after every LateEntryRecord is created.
    If monthly penalized late count >= threshold, auto-create half-day leave.
    """
    from .models import LateEntryRecord, LeaveApplication, LeaveBalance
    from payroll.models import LateEntryPolicy

    # 1. Count penalized late entries for this month
    count = LateEntryRecord.objects.filter(
        user=user,
        date__month=month,
        date__year=year,
        is_penalized=True,
    ).count()

    # 2. Get policy
    branch_id = getattr(user, 'branch_id', None)
    if not branch_id:
        if hasattr(user, 'faculty_profile'):
            branch_id = user.faculty_profile.branch_id
    if not branch_id:
        return

    policy = LateEntryPolicy.objects.filter(branch_id=branch_id, is_active=True).first()
    if not policy:
        return

    # 3. Check if auto_halfday_deduction is enabled
    if not policy.auto_halfday_deduction:
        return

    # 4. Check threshold
    if count < policy.late_entry_threshold:
        return

    # 5. Idempotent check: only one auto-deduction per user per month
    today = timezone.now().date()
    existing = LeaveApplication.objects.filter(
        applied_by=user,
        is_auto_generated=True,
        from_date__month=month,
        from_date__year=year,
    ).exists()
    if existing:
        return

    # 6. Auto-create half-day leave
    # Try casual first, fall back to unpaid if balance exhausted
    leave_type = 'casual'
    balance = LeaveBalance.objects.filter(
        user=user, leave_type='casual', year=year,
    ).first()
    if not balance or balance.remaining_days < Decimal('0.5'):
        leave_type = 'unpaid'

    leave = LeaveApplication.objects.create(
        applied_by=user,
        branch_id=branch_id,
        leave_type=leave_type,
        from_date=today,
        to_date=today,
        is_half_day=True,
        total_days=Decimal('0.5'),
        reason=f"Auto-deducted: {count} late entries in {month}/{year}",
        is_auto_generated=True,
        status='approved',
    )

    # Deduct balance
    if leave_type != 'unpaid' and balance:
        balance.used_days += Decimal('0.5')
        balance.save(update_fields=['used_days'])

    # Mark latest LateEntryRecord
    latest = LateEntryRecord.objects.filter(
        user=user,
        date__month=month,
        date__year=year,
        is_penalized=True,
    ).order_by('-date', '-created_at').first()
    if latest:
        latest.auto_deduction_triggered = True
        latest.save(update_fields=['auto_deduction_triggered'])

    # Notify user
    notify(
        str(user.id),
        title="Half-day auto-deducted",
        body=f"You have {count} late entries this month. 0.5 leave day auto-deducted.",
        metadata={"month": month, "year": year},
        email_template='emails/leave_auto_deducted.html',
        email_context={
            'user_name': user.name,
            'late_entries_count': count,
            'month': month,
            'year': year
        }
    )
    # WhatsApp: leave_auto_deducted_ to the employee
    try:
        if getattr(user, 'phone', None):
            from chat.notifications import send_whatsapp_with_fallback
            send_whatsapp_with_fallback(
                to=user.phone,
                template_name="leave_auto_deducted_",
                language_code="en",
                components=[{
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": user.name},
                        {"type": "text", "text": str(count)},
                        {"type": "text", "text": str(month)},
                        {"type": "text", "text": str(year)},
                    ]
                }],
                fallback_body=(
                    f"Hello {user.name},\n\n"
                    f"0.5 days of leave have been auto-deducted from your balance due to {count} late entries in {month}/{year}.\n\n"
                    "Please adhere to timing policies to avoid further deductions."
                ),
                user_id=str(user.id),
            )
    except Exception as wa_err:
        logger.error(f"[Leave Auto-Deducted] WhatsApp to user {user.id} failed: {wa_err}")

    logger.info(f"Auto half-day deduction for user={user.id}, month={month}/{year}")


# ── WhatsApp Student Leave Parent Approval Handlers ───────────────────────────

def parse_student_leave_payload(payload_str, text_str=""):
    """
    Parses payload string (and optional text) to extract student leave action and ID.
    Returns (action, leave_id) or (None, None).
    """
    if not payload_str and not text_str:
        return None, None

    s = str(payload_str or "").strip()
    t = str(text_str or "").strip().lower()

    action = None
    leave_id = None

    if s.startswith("approve_student_leave_"):
        action = "approve"
        leave_id = s[len("approve_student_leave_"):]
    elif s.startswith("reject_student_leave_"):
        action = "reject"
        leave_id = s[len("reject_student_leave_"):]
    elif s.startswith("student_leave_approve_"):
        action = "approve"
        leave_id = s[len("student_leave_approve_"):]
    elif s.startswith("student_leave_reject_"):
        action = "reject"
        leave_id = s[len("student_leave_reject_"):]
    elif s.startswith("approve_leave_"):
        action = "approve"
        leave_id = s[len("approve_leave_"):]
    elif s.startswith("reject_leave_"):
        action = "reject"
        leave_id = s[len("reject_leave_"):]
    elif ":" in s:
        parts = s.split(":")
        if len(parts) >= 2:
            if parts[0] in ("approve_student_leave", "student_leave_approve", "approve"):
                action = "approve"
                leave_id = parts[-1]
            elif parts[0] in ("reject_student_leave", "student_leave_reject", "reject"):
                action = "reject"
                leave_id = parts[-1]

    # If action wasn't matched from prefix, check if payload is a raw UUID or text contains approve/reject
    if not action:
        if "approve" in t:
            action = "approve"
        elif "reject" in t:
            action = "reject"

        if action and not leave_id:
            try:
                import uuid
                uuid_obj = uuid.UUID(s)
                leave_id = str(uuid_obj)
            except (ValueError, TypeError):
                pass

    return action, leave_id


def handle_student_leave_whatsapp_approval(sender_wa_id, payload_str, text_str=""):
    """
    Handles parent approval/rejection for a student leave request triggered via WhatsApp template/interactive buttons.
    Returns True if processed as a student leave button reply, False otherwise.
    """
    action, leave_id = parse_student_leave_payload(payload_str, text_str)
    if not action:
        return False

    from .models import StudentLeaveApplication
    from django.contrib.auth import get_user_model
    from students.models import ParentLink
    from chat.notifications import send_whatsapp_text, send_system_notification
    from django.db.models import Q
    from django.conf import settings

    User = get_user_model()
    phone_clean = str(sender_wa_id or '').strip()
    if phone_clean.startswith('91') and len(phone_clean) == 12:
        phone_clean = phone_clean[2:]

    # Resolve parent user by sender_wa_id
    parent_user = User.objects.filter(
        Q(phone=sender_wa_id) |
        Q(phone=phone_clean) |
        Q(phone=f'+91{phone_clean}') |
        Q(phone=f'+{sender_wa_id}')
    ).first()

    # If leave_id is not specified in payload but action is approve/reject, try finding single pending leave for this parent
    if not leave_id and parent_user:
        pending = StudentLeaveApplication.objects.filter(
            student__parent_links__parent=parent_user,
            status='pending',
            parent_consulted=False
        ).order_by('-created_at')
        if pending.count() == 1:
            leave_id = str(pending.first().id)

    if not leave_id:
        logger.warning("[WA LEAVE APPROVAL] Could not identify leave_id for action=%s from sender=%s", action, sender_wa_id)
        return False

    try:
        app = StudentLeaveApplication.objects.select_related('student', 'student__branch', 'student__user').get(id=leave_id)
    except (StudentLeaveApplication.DoesNotExist, ValueError, TypeError):
        logger.warning("[WA LEAVE APPROVAL] StudentLeaveApplication id=%s not found.", leave_id)
        send_whatsapp_text(to=sender_wa_id, body="Student leave request not found.")
        return True

    student_name = getattr(app.student, 'full_name', None) or getattr(app.student, 'first_name', None) or str(app.student)

    # Check status
    if app.status != 'pending':
        send_whatsapp_text(
            to=sender_wa_id,
            body=f"This leave request for {student_name} has already been {app.status}."
        )
        return True

    if app.parent_consulted and action == 'approve':
        send_whatsapp_text(
            to=sender_wa_id,
            body=f"Parent approval for {student_name}'s leave ({app.from_date} to {app.to_date}) has already been recorded."
        )
        return True

    # Validate parent authorization
    is_parent = False
    if parent_user:
        is_parent = ParentLink.objects.filter(parent=parent_user, student=app.student).exists()

    if not is_parent:
        parent_links = ParentLink.objects.filter(student=app.student).select_related('parent')
        for pl in parent_links:
            p = pl.parent
            if p and p.phone:
                p_phone = str(p.phone).replace('+', '').strip()
                if p_phone.endswith(phone_clean) or phone_clean.endswith(p_phone):
                    is_parent = True
                    parent_user = p
                    break

    if not is_parent:
        logger.warning("[WA LEAVE APPROVAL] Sender %s is not linked as parent for student %s", sender_wa_id, app.student)
        send_whatsapp_text(
            to=sender_wa_id,
            body=f"Unauthorized: Your phone number is not registered as a parent for {student_name}."
        )
        return True

    now = timezone.now()

    if action == 'approve':
        app.parent_consulted = True
        app.parent_signature_date = now.date()
        if parent_user:
            app.received_by = parent_user
        app.save(update_fields=['parent_consulted', 'parent_signature_date', 'received_by'])

        # Confirm approval to parent via leave_status_update_ template
        try:
            from chat.notifications import send_whatsapp_with_fallback
            parent_name = getattr(parent_user, 'name', 'Parent') if parent_user else 'Parent'
            send_whatsapp_with_fallback(
                to=sender_wa_id,
                template_name="leave_status_update_",
                language_code="en",
                components=[{
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": parent_name},
                        {"type": "text", "text": app.leave_type},
                        {"type": "text", "text": "approved"},
                        {"type": "text", "text": parent_name},
                        {"type": "text", "text": ""},
                    ]
                }],
                fallback_body=f"\u2705 You have APPROVED the leave request for {student_name} ({app.from_date} to {app.to_date}). It is now pending final approval by the institute admin.",
                user_id=str(parent_user.id) if parent_user else None,
            )
        except Exception as wa_err:
            logger.error("[WA LEAVE APPROVAL] Template confirmation to parent failed: %s", wa_err)
            send_whatsapp_text(
                to=sender_wa_id,
                body=f"\u2705 You have APPROVED the leave request for {student_name} ({app.from_date} to {app.to_date}). It is now pending final approval by the institute admin."
            )

        # Notify admins
        try:
            from .views import STUDENT_LEAVE_ADMIN_ROLES
        except Exception:
            STUDENT_LEAVE_ADMIN_ROLES = ['super_admin', 'branch_manager', 'admin_senior_executive']

        try:
            org = getattr(getattr(app.student, 'branch', None), 'organization', None)
            bid = getattr(app.student, 'branch_id', None)
            admin_qs = User.objects.filter(role__in=STUDENT_LEAVE_ADMIN_ROLES, is_active=True)
            if org:
                admin_qs = admin_qs.filter(organization=org)
            if bid:
                admin_qs = admin_qs.filter(Q(branch_id=bid) | Q(branch_id__isnull=True))

            for admin_user in admin_qs:
                send_system_notification(
                    user_id=str(admin_user.id),
                    title="Student Leave Ready for Admin Approval",
                    body=f"Parent approval completed via WhatsApp for {student_name}'s {app.leave_type} leave ({app.from_date} to {app.to_date}).",
                    metadata={"student_leave_id": str(app.id), "step": "admin_approval"},
                )
        except Exception as admin_err:
            logger.error("[WA LEAVE APPROVAL] Failed notifying admins: %s", admin_err)

    elif action == 'reject':
        app.status = 'rejected'
        app.rejection_reason = "Rejected by parent via WhatsApp"
        if parent_user:
            app.reviewed_by = parent_user
        app.reviewed_at = now
        app.save(update_fields=['status', 'rejection_reason', 'reviewed_by', 'reviewed_at'])

        parent_name = getattr(parent_user, 'name', 'Parent') if parent_user else 'Parent'
        rejection_reason = "Rejected by parent via WhatsApp"

        # Confirm rejection to parent via leave_status_update_ template
        try:
            from chat.notifications import send_whatsapp_with_fallback
            send_whatsapp_with_fallback(
                to=sender_wa_id,
                template_name="leave_status_update_",
                language_code="en",
                components=[{
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": parent_name},
                        {"type": "text", "text": app.leave_type},
                        {"type": "text", "text": "rejected"},
                        {"type": "text", "text": parent_name},
                        {"type": "text", "text": rejection_reason},
                    ]
                }],
                fallback_body=f"\u274c You have REJECTED the leave request for {student_name} ({app.from_date} to {app.to_date}).",
                user_id=str(parent_user.id) if parent_user else None,
            )
        except Exception as wa_err:
            logger.error("[WA LEAVE APPROVAL] Template rejection confirmation to parent failed: %s", wa_err)
            send_whatsapp_text(
                to=sender_wa_id,
                body=f"\u274c You have REJECTED the leave request for {student_name} ({app.from_date} to {app.to_date})."
            )

        # Notify student via leave_status_update_ template + in-app notification
        try:
            if hasattr(app.student, 'user') and app.student.user and app.student.user.id:
                send_system_notification(
                    user_id=str(app.student.user.id),
                    title="Student Leave Rejected by Parent",
                    body=f"Your {app.leave_type} leave request was rejected by parent via WhatsApp.",
                    metadata={"student_leave_id": str(app.id), "status": "rejected"},
                )
                # WhatsApp to student
                student_phone = getattr(app.student.user, 'phone', None)
                if student_phone:
                    try:
                        from chat.notifications import send_whatsapp_with_fallback
                        student_name_str = getattr(app.student.user, 'name', student_name)
                        send_whatsapp_with_fallback(
                            to=student_phone,
                            template_name="leave_status_update_",
                            language_code="en",
                            components=[{
                                "type": "body",
                                "parameters": [
                                    {"type": "text", "text": student_name_str},
                                    {"type": "text", "text": app.leave_type},
                                    {"type": "text", "text": "rejected"},
                                    {"type": "text", "text": parent_name},
                                    {"type": "text", "text": rejection_reason},
                                ]
                            }],
                            fallback_body=f"Hello {student_name_str}, your {app.leave_type} leave request was rejected by {parent_name} via WhatsApp.",
                            user_id=str(app.student.user.id),
                        )
                    except Exception as st_wa_err:
                        logger.error("[WA LEAVE APPROVAL] Template notification to student failed: %s", st_wa_err)
        except Exception as st_err:
            logger.error("[WA LEAVE APPROVAL] Failed notifying student: %s", st_err)

    return True


def send_student_leave_whatsapp_request(parent_user, student, app):
    """
    Sends WhatsApp notification with template quick-reply buttons or interactive buttons
    to a parent asking for approval of a student leave application.
    """
    if not parent_user or not getattr(parent_user, 'phone', None):
        return

    from django.conf import settings

    student_name = student.full_name or student.first_name or "Your child"
    leave_type_display = getattr(app, 'leave_type_display', app.leave_type)

    body_text = (
        f"📋 *Student Leave Request*\n\n"
        f"Student: *{student_name}*\n"
        f"Leave Type: *{leave_type_display}*\n"
        f"Dates: *{app.from_date}* to *{app.to_date}*\n"
        f"Reason: {app.reason}\n\n"
        f"Please approve or reject this leave request using the buttons below."
    )

    template_name = getattr(settings, 'WHATSAPP_STUDENT_LEAVE_TEMPLATE', None)

    if template_name:
        try:
            from chat.notifications import send_whatsapp_template
            components = [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": str(student_name)},
                        {"type": "text", "text": str(leave_type_display)},
                        {"type": "text", "text": str(app.from_date)},
                        {"type": "text", "text": str(app.to_date)},
                        {"type": "text", "text": str(app.reason)[:50]},
                    ]
                },
                {
                    "type": "button",
                    "sub_type": "quick_reply",
                    "index": "0",
                    "parameters": [{"type": "payload", "payload": f"approve_student_leave_{app.id}"}]
                },
                {
                    "type": "button",
                    "sub_type": "quick_reply",
                    "index": "1",
                    "parameters": [{"type": "payload", "payload": f"reject_student_leave_{app.id}"}]
                }
            ]
            send_whatsapp_template(
                to=parent_user.phone,
                template_name=template_name,
                components=components,
                user_id=str(parent_user.id),
                fallback_body=body_text
            )
            logger.info("[WA LEAVE] Template button request sent to parent %s", parent_user.phone)
            return
        except Exception as e:
            logger.warning("[WA LEAVE] Template send failed for parent %s (%s) — falling back to interactive buttons.", parent_user.phone, e)

    # Fallback to interactive buttons
    try:
        from core.utils import _get_sender
        sender = _get_sender()
        sender.send_interactive_buttons(
            to=parent_user.phone,
            body_text=body_text,
            buttons=[
                {"id": f"approve_student_leave_{app.id}", "title": "Approve Leave"},
                {"id": f"reject_student_leave_{app.id}", "title": "Reject Leave"}
            ]
        )
        logger.info("[WA LEAVE] Interactive button request sent to parent %s", parent_user.phone)
    except Exception as exc:
        logger.warning("[WA LEAVE] Interactive button send failed: %s. Sending text fallback.", exc)
        from chat.notifications import send_whatsapp_text
        text_fallback = body_text + "\n\nReply 'Approve' or 'Reject' to respond."
        send_whatsapp_text(to=parent_user.phone, body=text_fallback, user_id=str(parent_user.id))

