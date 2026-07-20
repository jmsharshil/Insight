"""
Attendance background tasks — v3 FRD §4.4 aligned.

Changes from v2:
- detect_missing_scans: CASE 1 (missing OUT) + CASE 2 (missing IN)
  with correct alert types: missing_checkout_scan / missing_checkin_scan
- check_no_checkout_eod: uses missing_checkout_scan alert type
- All stub notify() calls replaced with real notification helpers
- detect_missing_scans and check_no_checkout_eod wired to scheduler
"""

import logging
from django.utils import timezone

logger = logging.getLogger(__name__)


# ── Notification helper ───────────────────────────────────────────────────────

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

# ═══════════════════════════════════════════════════════════════════════════════
# 1. check_checkin_delay_15  (FRD §4.4.2: 15-min delay → Parent only)
# ═══════════════════════════════════════════════════════════════════════════════

def check_checkin_delay_15(student_id, date_str, session=None):
    """
    Scheduled at (slot start + 15 min). If still not checked in → alert Parent.
    Updated for multiple sessions per day (no longer filters on legacy 'session' field).
    """
    from .models import AttendanceRecord, AlertLog

    try:
        record = AttendanceRecord.objects.filter(
            student_id=student_id, date=date_str
        ).order_by('-checked_in_at').first()

        if record and record.checked_in_at:
            return f"Student {student_id} already checked in."

        # Fetch student for notification
        student = None
        try:
            from django.apps import apps
            SP = apps.get_model('students', 'Student')
            student = SP.objects.select_related('user').get(id=student_id)
        except Exception:
            pass

        alert = AlertLog.objects.create(
            student_id=student_id,
            alert_type='checkin_delay_15',
            message='15-minute delay alert: Student has not checked in for today\'s session.',
            notified_parent=True,
            notified_admin=False,
        )
        logger.info(f"15-min delay alert for student {student_id} on {date_str}")

        # Notify parent about missing check-in at 15-min mark
        if student:
            try:
                from .notifications import notify_student_missing_scan
                import datetime
                date_obj = datetime.datetime.strptime(date_str, '%Y-%m-%d').date() if isinstance(date_str, str) else date_str
                notify_student_missing_scan(student, 'no_checkin', date_obj)
            except Exception as ne:
                logger.warning(f"15-min delay notification failed for {student_id}: {ne}")

        return f"15-min alert created for {student_id}"

    except Exception as exc:
        logger.error(f"check_checkin_delay_15 error: {exc}")
        raise exc


# ═══════════════════════════════════════════════════════════════════════════════
# 2. check_checkin_delay_30  (FRD §4.4.2: 30-min delay → Parent AND Admin)
# ═══════════════════════════════════════════════════════════════════════════════

def check_checkin_delay_30(student_id, date_str, branch_id=None, session=None):
    """
    Escalation at slot start + 30 min.
    Alert both Parent AND branch Admin.
    Updated to not rely on legacy 'session' field.
    """
    from .models import AttendanceRecord, AlertLog

    try:
        record = AttendanceRecord.objects.filter(
            student_id=student_id, date=date_str
        ).order_by('-checked_in_at').first()

        if record and record.checked_in_at:
            return f"Student {student_id} checked in (late)."

        # Fetch student for notification
        student = None
        try:
            from django.apps import apps
            SP = apps.get_model('students', 'Student')
            student = SP.objects.select_related('user').get(id=student_id)
        except Exception:
            pass

        AlertLog.objects.create(
            student_id=student_id,
            alert_type='checkin_delay_30',
            message='ESCALATION: Student has not checked in within 30 minutes of session.',
            notified_parent=True,
            notified_admin=True,
        )
        logger.info(f"30-min escalation alert for student {student_id} on {date_str}")

        # Notify parent (30-min escalation)
        if student:
            try:
                from .notifications import notify_student_missing_scan
                import datetime
                date_obj = datetime.datetime.strptime(date_str, '%Y-%m-%d').date() if isinstance(date_str, str) else date_str
                notify_student_missing_scan(student, 'no_checkin', date_obj)
            except Exception as ne:
                logger.warning(f"30-min escalation notification failed for {student_id}: {ne}")

        # Notify branch admin via system notification
        if branch_id:
            try:
                from django.contrib.auth import get_user_model
                User = get_user_model()
                admins = User.objects.filter(
                    branch_id=branch_id,
                    role__in=['branch_manager', 'admin_senior_executive', 'admin_executive'],
                    is_active=True,
                )
                student_name = getattr(student, 'first_name', str(student_id)) if student else str(student_id)
                for admin in admins:
                    notify(
                        admin.id,
                        'Student Not Checked In — 30 Min',
                        f"{student_name} has not checked in 30 minutes after session start on {date_str}.",
                        {'module': 'attendance', 'student_id': str(student_id), 'type': 'checkin_delay_30'}
                    )
            except Exception as ne:
                logger.warning(f"Admin escalation notification failed: {ne}")

        return f"30-min escalation alert created for {student_id}"

    except Exception as exc:
        logger.error(f"check_checkin_delay_30 error: {exc}")
        raise exc


# ═══════════════════════════════════════════════════════════════════════════════
# 3. check_no_checkout_eod  (fires at batch.session_end)
#    v3: uses 'missing_checkout_scan' alert type, notifies Parent only
# ═══════════════════════════════════════════════════════════════════════════════

def check_no_checkout_eod(student_id, date_str, session=None):
    """
    Fired at session end time.
    If student checked in but never checked out → violation + alert.
    Updated for new multiple-record model (uses most recent open record).
    """
    from .models import AttendanceRecord, AlertLog, ViolationRecord

    try:
        record = AttendanceRecord.objects.filter(
            student_id=student_id,
            date=date_str,
            checked_in_at__isnull=False,
            checked_out_at__isnull=True,
        ).order_by('-checked_in_at').first()

        if not record:
            return "No open check-in found — skip."

        if record.checked_out_at:
            return "Already checked out."

        # Fetch student for notification
        student = None
        try:
            from django.apps import apps
            SP = apps.get_model('students', 'Student')
            student = SP.objects.select_related('user').get(id=student_id)
        except Exception:
            pass

        # v3: use missing_checkout_scan alert type
        AlertLog.objects.create(
            student_id=student_id,
            alert_type='missing_checkout_scan',
            message=f'Missing check-out scan: Student checked in at {record.checked_in_at:%H:%M} but did not check out.',
            notified_parent=True,
            notified_admin=False,
        )

        ViolationRecord.objects.create(
            student_id=student_id,
            violation_type='missing_checkout',
            date=date_str,
            description='No check-out recorded for session.',
            logged_by_admin=False,
            created_by=None,
        )
        logger.info(f"No-checkout violation for student {student_id} on {date_str}")

        # Notify parent about missing check-out
        if student:
            try:
                from .notifications import notify_student_missing_scan
                import datetime
                date_obj = datetime.datetime.strptime(date_str, '%Y-%m-%d').date() if isinstance(date_str, str) else date_str
                notify_student_missing_scan(
                    student, 'no_checkout', date_obj, checkin_time=record.checked_in_at
                )
            except Exception as ne:
                logger.warning(f"No-checkout notification failed for {student_id}: {ne}")

        # Check violation threshold
        check_violation_threshold(student_id)

        return f"No-checkout violation created for {student_id}"

    except Exception as exc:
        logger.error(f"check_no_checkout_eod error: {exc}")
        raise exc


# ═══════════════════════════════════════════════════════════════════════════════
# 4. detect_missing_scans  (v3: rewritten per FRD §4.4.2)
#    Nightly at 23:00 for each branch.
#    CASE 1 — missing OUT (IN exists, OUT does not) → missing_checkout_scan
#    CASE 2 — missing IN (no IN for scheduled session) → missing_checkin_scan
# ═══════════════════════════════════════════════════════════════════════════════

def detect_missing_scans(branch_id, date_str=None):
    """
    Run at end of each day (23:00).
    For every student with a scheduled batch session today:
      CASE 1 - Missing OUT scan: IN exists, OUT does not → missing_checkout_scan (Parent) + violation
      CASE 2 - Missing IN scan: no IN scan at all → missing_checkin_scan (Parent) + no_show violation
    A student missing both triggers Case 2 only.
    Uses AttendanceRecord for accuracy with multi-session support.
    """
    from .models import AttendanceRecord, AlertLog, ViolationRecord
    from .notifications import notify_student_missing_scan
    from django.apps import apps

    if date_str is None:
        date_str = timezone.localtime(timezone.now()).date().strftime('%Y-%m-%d')

    import datetime
    date_obj = datetime.datetime.strptime(date_str, '%Y-%m-%d').date() if isinstance(date_str, str) else date_str

    try:
        SP = apps.get_model('students', 'Student')
        students = SP.objects.filter(
            branch_id=branch_id, is_active=True
        ).select_related('user')

        processed = 0
        for student in students:
            # Get all attendance records for the day (supports multiple sessions)
            day_records = list(AttendanceRecord.objects.filter(
                student=student,
                date=date_str
            ))

            has_any_checkin = any(r.checked_in_at for r in day_records)
            open_sessions = [r for r in day_records if r.checked_in_at and not r.checked_out_at]

            if not has_any_checkin:
                # CASE 2: Missing check-in scan (no_show) — avoid duplicate alerts
                if AlertLog.objects.filter(
                    student=student,
                    alert_type='missing_checkin_scan',
                    sent_at__date=date_obj,
                ).exists():
                    continue

                AlertLog.objects.create(
                    student=student,
                    alert_type='missing_checkin_scan',
                    message=f'Missing check-in scan / no-show on {date_str}.',
                    notified_parent=True,
                    notified_admin=False,
                )
                ViolationRecord.objects.create(
                    student=student,
                    violation_type='no_show',
                    date=date_str,
                    description='No check-in recorded for scheduled class.',
                    logged_by_admin=False,
                )
                try:
                    notify_student_missing_scan(student, 'no_checkin', date_obj)
                except Exception as ne:
                    logger.warning(f"Notification failed for no_show {student.id}: {ne}")
                check_violation_threshold(student.id)
                processed += 1

            elif open_sessions:
                # CASE 1: Has check-in but missing checkout
                for open_rec in open_sessions:
                    if AlertLog.objects.filter(
                        student=student,
                        alert_type='missing_checkout_scan',
                        sent_at__date=date_obj,
                    ).exists():
                        continue

                    AlertLog.objects.create(
                        student=student,
                        alert_type='missing_checkout_scan',
                        message=f'Missing check-out scan. Checked in at {open_rec.checked_in_at} but no checkout.',
                        notified_parent=True,
                        notified_admin=False,
                    )
                    ViolationRecord.objects.create(
                        student=student,
                        violation_type='missing_checkout',
                        date=date_str,
                        description=f'Missing checkout for session starting at {open_rec.checked_in_at}.',
                        logged_by_admin=False,
                    )
                    try:
                        notify_student_missing_scan(
                            student, 'no_checkout', date_obj, checkin_time=open_rec.checked_in_at
                        )
                    except Exception as ne:
                        logger.warning(f"Notification failed for missing_checkout {student.id}: {ne}")
                    check_violation_threshold(student.id)
                    processed += 1

        logger.info(f"Missing scan detection complete for branch {branch_id} on {date_str}: {processed} issues found")
        return f"Detection completed: {processed} issues found."

    except Exception as exc:
        logger.error(f"detect_missing_scans error for branch {branch_id}: {exc}")
        return f"Error: {exc}"


# ═══════════════════════════════════════════════════════════════════════════════
# 4b. detect_missing_scans_all_branches  (scheduler entry point)
#     Runs detect_missing_scans for every active branch.
# ═══════════════════════════════════════════════════════════════════════════════

def detect_missing_scans_all_branches():
    """
    Nightly task: runs detect_missing_scans for all active branches.
    Registered as 'detect_missing_scans_all_branches' in the scheduler.
    """
    try:
        from branch.models import Branch
        branches = Branch.objects.filter(is_active=True)
        date_str = timezone.localtime(timezone.now()).date().strftime('%Y-%m-%d')
        results = []
        for branch in branches:
            result = detect_missing_scans(str(branch.id), date_str)
            results.append(f"Branch {branch.name}: {result}")
        logger.info(f"Nightly missing scan detection done for {len(results)} branches.")
        return "\n".join(results)
    except Exception as exc:
        logger.error(f"detect_missing_scans_all_branches error: {exc}")
        return f"Error: {exc}"


# ═══════════════════════════════════════════════════════════════════════════════
# 5. check_violation_threshold  (v3: actually updates qr_blocked on StudentProfile)
# ═══════════════════════════════════════════════════════════════════════════════

def check_violation_threshold(student_id):
    """
    Called after any ViolationRecord is created or resolved.
    If unresolved violations >= 3 → block QR + alert admin.
    Else → re-enable QR if it was blocked.
    """
    from .models import AlertLog
    from .utils import get_active_violations_count, should_block_qr

    count = get_active_violations_count(student_id)

    try:
        from django.apps import apps
        SP = apps.get_model('students', 'Student')
    except Exception:
        SP = None

    if should_block_qr(student_id):
        # Block QR
        if SP:
            SP.objects.filter(id=student_id).update(qr_blocked=True)

        # Avoid duplicate alert on same day
        if not AlertLog.objects.filter(
            student_id=student_id, alert_type='violation',
            sent_at__date=timezone.now().date(),
        ).exists():
            AlertLog.objects.create(
                student_id=student_id,
                alert_type='violation',
                message=f'{count} active violations. QR access has been blocked.',
                notified_admin=True,
            )

        logger.info(f"QR blocked for student {student_id} ({count} violations)")
    else:
        # Re-enable QR if was blocked
        if SP:
            SP.objects.filter(id=student_id).update(qr_blocked=False)

    return f"Violations for {student_id}: {count}"


# ═══════════════════════════════════════════════════════════════════════════════
# 6. send_low_attendance_alerts  (weekly periodic or on-demand)
# ═══════════════════════════════════════════════════════════════════════════════

def send_low_attendance_alerts(branch_id, threshold=75.0):
    """
    Periodic task (weekly or on-demand).
    Computes attendance % for each active student and creates alerts.
    """
    from .models import AlertLog
    from .utils import compute_attendance_percentage
    from .notifications import notify_student_low_attendance

    try:
        from django.apps import apps
        SP = apps.get_model('students', 'Student')
        students = SP.objects.filter(branch_id=branch_id)
        if hasattr(SP, 'is_active'):
            students = students.filter(is_active=True)
    except Exception as e:
        logger.error(f"Cannot load Student model: {e}")
        return "Student model unavailable"

    alerts = 0
    for s in students:
        present, total, pct = compute_attendance_percentage(s.id)
        if total == 0:
            continue
        if pct < threshold:
            if AlertLog.objects.filter(
                student=s, alert_type='low_attendance',
                sent_at__date=timezone.now().date(),
            ).exists():
                continue
            AlertLog.objects.create(
                student=s, alert_type='low_attendance',
                message=f'Weekly alert: {pct}% attendance below {threshold}% threshold.',
                threshold=threshold, current_pct=pct,
                notified_parent=True,
            )
            try:
                notify_student_low_attendance(s, pct, threshold)
            except Exception as ne:
                logger.warning(f"Low attendance notification failed for {s.id}: {ne}")
            alerts += 1

    logger.info(f"Low attendance alerts: {alerts} for branch {branch_id}")
    return f"{alerts} alerts created"
