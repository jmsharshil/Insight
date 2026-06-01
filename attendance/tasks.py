"""
Attendance Celery tasks — v3 FRD §4.4 aligned.

Changes from v2:
- detect_missing_scans: split into CASE 1 (missing OUT) + CASE 2 (missing IN)
  with correct alert types: missing_checkout_scan / missing_checkin_scan
- check_no_checkout_eod: uses missing_checkout_scan alert type
- check_violation_threshold: actually updates Student.qr_blocked
- Notification stubs use: notify(recipient_user_id, title, body, metadata)
"""

import logging
from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


# ── Stub notification helper ──────────────────────────────────────────────────

def notify(recipient_user_id, title, body, metadata=None):
    """Stub: push/in-app notification. Replace with real implementation."""
    logger.info(f"NOTIFY [{recipient_user_id}] {title}: {body}")


# ═══════════════════════════════════════════════════════════════════════════════
# 1. check_checkin_delay_15  (FRD §4.4.2: 15-min delay → Parent only)
# ═══════════════════════════════════════════════════════════════════════════════

@shared_task(bind=True, max_retries=2)
def check_checkin_delay_15(self, student_id, date_str, session):
    """
    Scheduled at (batch.session_start + 15 min) for every active student.
    If still not checked in → alert Parent, then schedule 30-min escalation.
    """
    from .models import AttendanceRecord, AlertLog

    try:
        record = AttendanceRecord.objects.filter(
            student_id=student_id, date=date_str, session=session,
        ).first()

        if record and record.checked_in_at:
            return f"Student {student_id} already checked in."

        alert = AlertLog.objects.create(
            student_id=student_id,
            alert_type='checkin_delay_15',
            message=f'15-minute delay alert: Student has not checked in for {session} session.',
            notified_parent=True,
            notified_admin=False,
        )
        logger.info(f"15-min delay alert for student {student_id} on {date_str}")

        # Stub: notify Parent only (FRD §4.4.2)
        # notify(parent_user_id, "15-min delay", f"<Name> has not checked in", {})

        # Schedule 30-min escalation
        check_checkin_delay_30.apply_async(
            args=[student_id, date_str, session],
            countdown=900,  # 15 more minutes
        )

        return f"15-min alert created for {student_id}"

    except Exception as exc:
        logger.error(f"check_checkin_delay_15 error: {exc}")
        raise self.retry(exc=exc, countdown=60)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. check_checkin_delay_30  (FRD §4.4.2: 30-min delay → Parent AND Admin)
# ═══════════════════════════════════════════════════════════════════════════════

@shared_task(bind=True, max_retries=2)
def check_checkin_delay_30(self, student_id, date_str, session):
    """
    Escalation at session_start + 30 min.
    Alert both Parent AND branch Admin.
    """
    from .models import AttendanceRecord, AlertLog

    try:
        record = AttendanceRecord.objects.filter(
            student_id=student_id, date=date_str, session=session,
        ).first()

        if record and record.checked_in_at:
            return f"Student {student_id} checked in (late)."

        AlertLog.objects.create(
            student_id=student_id,
            alert_type='checkin_delay_30',
            message=f'ESCALATION: Student has not checked in within 30 minutes of {session} session.',
            notified_parent=True,
            notified_admin=True,
        )
        logger.info(f"30-min escalation alert for student {student_id} on {date_str}")

        # Stub: notify Parent AND Admin (FRD §4.4.2)
        # notify(parent_user_id, "30-min escalation", ...)
        # notify(admin_user_id, "30-min escalation", ...)

        return f"30-min escalation alert created for {student_id}"

    except Exception as exc:
        logger.error(f"check_checkin_delay_30 error: {exc}")
        raise self.retry(exc=exc, countdown=60)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. check_no_checkout_eod  (fires at batch.session_end)
#    v3: uses 'missing_checkout_scan' alert type, notifies Parent only
# ═══════════════════════════════════════════════════════════════════════════════

@shared_task(bind=True, max_retries=2)
def check_no_checkout_eod(self, student_id, date_str, session):
    """
    Fired at session end time.
    If student checked in but never checked out → violation + alert.
    FRD §4.4.2: missing_checkout_scan → notify Parent only.
    """
    from .models import AttendanceRecord, AlertLog, ViolationRecord

    try:
        record = AttendanceRecord.objects.filter(
            student_id=student_id, date=date_str, session=session,
        ).first()

        if not record or not record.checked_in_at:
            return "No check-in found — skip."

        if record.checked_out_at:
            return "Already checked out."

        # v3: use missing_checkout_scan alert type
        AlertLog.objects.create(
            student_id=student_id,
            alert_type='missing_checkout_scan',
            message=f'Missing check-out scan: Student checked in at {record.checked_in_at:%H:%M} but did not check out for {session} session.',
            notified_parent=True,
            notified_admin=False,
        )

        ViolationRecord.objects.create(
            student_id=student_id,
            violation_type='missing_checkout',
            date=date_str,
            description=f'No check-out recorded for {session} session.',
            logged_by_admin=False,
            created_by=None,
        )
        logger.info(f"No-checkout violation for student {student_id} on {date_str}")

        # Stub: notify Parent (FRD §4.4.2)
        # notify(parent_user_id, "Missing check-out", f"<Name> missing check-out scan", {})

        # Check violation threshold
        check_violation_threshold.delay(student_id)

        return f"No-checkout violation created for {student_id}"

    except Exception as exc:
        logger.error(f"check_no_checkout_eod error: {exc}")
        raise self.retry(exc=exc, countdown=60)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. detect_missing_scans  (v3: rewritten per FRD §4.4.2)
#    Nightly at 23:00 for each branch.
#    CASE 1 — missing OUT (IN exists, OUT does not) → missing_checkout_scan
#    CASE 2 — missing IN (no IN for scheduled session) → missing_checkin_scan
# ═══════════════════════════════════════════════════════════════════════════════

@shared_task(bind=True, max_retries=2)
def detect_missing_scans(self, branch_id, date_str):
    """
    Run at end of each day (23:00).
    For every student with a scheduled batch session today:
      CASE 1 - Missing OUT scan: IN exists, OUT does not → missing_checkout_scan (Parent)
      CASE 2 - Missing IN scan: no IN scan at all → missing_checkin_scan (Parent)
    A student missing both IN and OUT triggers Case 2 only.
    """
    from .models import QRScanLog, AlertLog

    try:
        # Get all students with active batches in this branch
        from django.apps import apps
        SP = apps.get_model('students', 'Student')
        students = SP.objects.filter(branch_id=branch_id, is_active=True, batch__isnull=False)

        for student in students:
            has_checkin = QRScanLog.objects.filter(
                student=student, scanned_at__date=date_str, scan_type='check_in',
            ).exists()
            has_checkout = QRScanLog.objects.filter(
                student=student, scanned_at__date=date_str, scan_type='check_out',
            ).exists()

            if not has_checkin:
                # CASE 2: No IN scan for scheduled session → missing_checkin_scan
                AlertLog.objects.create(
                    student=student,
                    alert_type='missing_checkin_scan',
                    message=f'Absent / Missing check-in alert: No check-in scan recorded on {date_str}.',
                    notified_parent=True,
                    notified_admin=False,
                )
                # Stub: notify Parent
                # notify(parent_user_id, "Missing check-in", f"<Name> absent / missing check-in", {})

            elif has_checkin and not has_checkout:
                # CASE 1: IN exists, no OUT → missing_checkout_scan
                AlertLog.objects.create(
                    student=student,
                    alert_type='missing_checkout_scan',
                    message=f'Missing check-out scan alert: Check-in recorded but no check-out on {date_str}.',
                    notified_parent=True,
                    notified_admin=False,
                )
                # Stub: notify Parent
                # notify(parent_user_id, "Missing check-out", f"<Name> missing check-out", {})

        logger.info(f"Missing scan detection complete for branch {branch_id} on {date_str}")
        return "Done"

    except Exception as exc:
        logger.error(f"detect_missing_scans error: {exc}")
        raise self.retry(exc=exc, countdown=60)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. check_violation_threshold  (v3: actually updates qr_blocked on StudentProfile)
# ═══════════════════════════════════════════════════════════════════════════════

@shared_task
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

        # Stub: notify Admin
        # notify(admin_user_id, "QR blocked", f"<Name> has {count} violations", {})

        logger.info(f"QR blocked for student {student_id} ({count} violations)")
    else:
        # Re-enable QR if was blocked
        if SP:
            SP.objects.filter(id=student_id).update(qr_blocked=False)

    return f"Violations for {student_id}: {count}"


# ═══════════════════════════════════════════════════════════════════════════════
# 6. send_low_attendance_alerts  (weekly periodic or on-demand)
# ═══════════════════════════════════════════════════════════════════════════════

@shared_task
def send_low_attendance_alerts(branch_id, threshold=75.0):
    """
    Periodic task (weekly or on-demand).
    Computes attendance % for each active student and creates alerts.
    """
    from .models import AlertLog
    from .utils import compute_attendance_percentage

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
            alerts += 1
            # Stub: notify Parent

    logger.info(f"Low attendance alerts: {alerts} for branch {branch_id}")
    return f"{alerts} alerts created"
