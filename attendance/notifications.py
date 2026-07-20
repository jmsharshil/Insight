"""
Centralized attendance notification helpers for students, parents, and staff.
"""
import logging
from django.conf import settings
from django.core.mail import EmailMessage
from django.utils import timezone
from chat.notifications import send_system_notification

logger = logging.getLogger(__name__)


def _get_parent_email(student):
    """Try to get parent email from the student profile."""
    if hasattr(student, 'parent_email') and student.parent_email:
        return student.parent_email
    return None


def _get_parent_user(student):
    """Try to get linked parent User from ParentLink."""
    try:
        from students.models import ParentLink
        link = ParentLink.objects.filter(student=student).select_related('parent').first()
        if link and link.parent:
            return link.parent
    except Exception:
        pass
    return None


def notify_student_attendance_marked(student, date, status_val, batch_name=None):
    """
    Notify student and parent when attendance is marked (batch marking).
    """
    if not student or not hasattr(student, 'user') or not student.user:
        return

    status_display = status_val.replace('_', ' ').title()
    batch_info = f" for batch {batch_name}" if batch_name else ""

    # Notify student
    send_system_notification(
        user_id=str(student.user.id),
        title='Attendance Marked',
        body=f"Your attendance for {date.strftime('%d %b %Y')}{batch_info} has been marked as {status_display}.",
        metadata={'module': 'attendance', 'date': str(date), 'status': status_val}
    )

    # Notify parent via system notification (if linked) and email
    parent_user = _get_parent_user(student)
    if parent_user:
        send_system_notification(
            user_id=str(parent_user.id),
            title='Attendance Update',
            body=f"{student.first_name}'s attendance for {date.strftime('%d %b %Y')}{batch_info} is marked as {status_display}.",
            metadata={'module': 'attendance', 'student_id': str(student.id), 'date': str(date)}
        )

    parent_email = _get_parent_email(student)
    if parent_email:
        try:
            email = EmailMessage(
                f"Attendance Update: {student.first_name}",
                f"Dear Parent,\n\n{student.first_name}'s attendance for {date.strftime('%d %b %Y')}{batch_info} has been marked as {status_display}.\n\nInsight Institute",
                settings.DEFAULT_FROM_EMAIL,
                [parent_email]
            )
            email.send(fail_silently=True)
        except Exception as e:
            logger.error(f"Failed to send attendance email to parent {parent_email}: {e}")


def notify_student_qr_scan(student, scan_type, scan_time, attendance_status='On Time'):
    """
    Notify parent when student checks in or out via QR.
    attendance_status: 'On Time', 'Late', 'Pending', 'Present', etc.
    """
    if not student:
        return

    action = 'checked in' if scan_type == 'check_in' else 'checked out'
    local_scan_time = timezone.localtime(scan_time) if timezone.is_aware(scan_time) else scan_time
    time_str = local_scan_time.strftime('%I:%M %p')
    date_str = local_scan_time.strftime('%d %b %Y')
    student_name = getattr(student, 'first_name', str(student))
    status_label = attendance_status or ('On Time' if scan_type == 'check_in' else 'Present')

    body = f"{student_name} has {action} at {time_str} on {date_str}. Status: {status_label}."

    # Notify parent via system notification
    parent_user = _get_parent_user(student)
    if parent_user:
        send_system_notification(
            user_id=str(parent_user.id),
            title=f'Student {action.title()}',
            body=body,
            metadata={
                'module': 'attendance',
                'student_id': str(student.id),
                'scan_type': scan_type,
                'status': status_label,
                'time': time_str,
            }
        )

    # Notify parent via email
    parent_email = _get_parent_email(student)
    if parent_email:
        try:
            email = EmailMessage(
                f"{student_name} has {action}",
                f"Dear Parent,\n\n{body}\n\nInsight Institute",
                settings.DEFAULT_FROM_EMAIL,
                [parent_email]
            )
            email.send(fail_silently=True)
        except Exception as e:
            logger.error(f"Failed to send QR scan email to parent {parent_email}: {e}")


def notify_student_missing_scan(student, event_type, date, checkin_time=None):
    """
    Notify parent (and student) about a missing check-in or check-out.
    event_type: 'no_checkin' | 'no_checkout'
    checkin_time: datetime of check-in (used only for no_checkout)
    """
    if not student:
        return

    student_name = getattr(student, 'first_name', str(student))
    date_str = date.strftime('%d %b %Y') if hasattr(date, 'strftime') else str(date)

    if event_type == 'no_checkin':
        title = f'Absent Alert: {student_name}'
        body = (
            f"{student_name} did not check in for class on {date_str}. "
            f"Status: Absent. Please contact the institute if this is unexpected."
        )
        student_body = f"You did not check in for class on {date_str}. Status: Absent."
    else:  # no_checkout
        checkin_str = ''
        if checkin_time:
            local_time = timezone.localtime(checkin_time) if timezone.is_aware(checkin_time) else checkin_time
            checkin_str = f" (checked in at {local_time.strftime('%I:%M %p')})"
        title = f'Missing Check-Out: {student_name}'
        body = (
            f"{student_name}{checkin_str} did not check out from class on {date_str}. "
            f"Status: Pending."
        )
        student_body = f"You did not check out from class on {date_str}. Status: Pending."

    # Notify student (if profile has user)
    if hasattr(student, 'user') and student.user:
        send_system_notification(
            user_id=str(student.user.id),
            title=title,
            body=student_body,
            metadata={'module': 'attendance', 'event': event_type, 'date': date_str}
        )

    # Notify parent via system notification
    parent_user = _get_parent_user(student)
    if parent_user:
        send_system_notification(
            user_id=str(parent_user.id),
            title=title,
            body=body,
            metadata={
                'module': 'attendance',
                'student_id': str(student.id),
                'event': event_type,
                'date': date_str,
            }
        )

    # Notify parent via email
    parent_email = _get_parent_email(student)
    if parent_email:
        try:
            email = EmailMessage(
                title,
                f"Dear Parent,\n\n{body}\n\nInsight Institute",
                settings.DEFAULT_FROM_EMAIL,
                [parent_email]
            )
            email.send(fail_silently=True)
        except Exception as e:
            logger.error(f"Failed to send missing scan email to parent {parent_email}: {e}")


def notify_student_low_attendance(student, pct, threshold):
    """
    Notify student and parent about low attendance alert.
    """
    if not student or not hasattr(student, 'user') or not student.user:
        return

    student_name = getattr(student, 'first_name', str(student))

    # Notify student
    send_system_notification(
        user_id=str(student.user.id),
        title='Low Attendance Warning',
        body=f"Your attendance is at {pct}%, which is below the {threshold}% threshold. Please improve your attendance.",
        metadata={'module': 'attendance', 'percentage': pct, 'threshold': threshold}
    )

    # Notify parent
    parent_user = _get_parent_user(student)
    if parent_user:
        send_system_notification(
            user_id=str(parent_user.id),
            title='Low Attendance Alert',
            body=f"{student_name}'s attendance is at {pct}%, below the {threshold}% threshold.",
            metadata={'module': 'attendance', 'student_id': str(student.id)}
        )

    parent_email = _get_parent_email(student)
    if parent_email:
        try:
            email = EmailMessage(
                f"Low Attendance Alert: {student_name}",
                f"Dear Parent,\n\n{student_name}'s attendance is currently at {pct}%, which is below the required {threshold}% threshold.\n\nPlease ensure regular attendance.\n\nInsight Institute",
                settings.DEFAULT_FROM_EMAIL,
                [parent_email]
            )
            email.send(fail_silently=True)
        except Exception as e:
            logger.error(f"Failed to send low attendance email to parent {parent_email}: {e}")


def notify_student_violation(student, violation_type, date, description=''):
    """
    Notify student and parent about an attendance violation.
    """
    if not student or not hasattr(student, 'user') or not student.user:
        return

    student_name = getattr(student, 'first_name', str(student))
    v_type = violation_type.replace('_', ' ').title()

    send_system_notification(
        user_id=str(student.user.id),
        title=f'Attendance Violation: {v_type}',
        body=f"An attendance violation ({v_type}) has been recorded for {date.strftime('%d %b %Y')}. {description}",
        metadata={'module': 'attendance', 'violation_type': violation_type}
    )

    parent_user = _get_parent_user(student)
    if parent_user:
        send_system_notification(
            user_id=str(parent_user.id),
            title=f'Attendance Violation: {student_name}',
            body=f"A violation ({v_type}) has been recorded for {student_name} on {date.strftime('%d %b %Y')}.",
            metadata={'module': 'attendance', 'student_id': str(student.id)}
        )

    parent_email = _get_parent_email(student)
    if parent_email:
        try:
            email = EmailMessage(
                f"Attendance Violation: {student_name}",
                f"Dear Parent,\n\nAn attendance violation ({v_type}) has been recorded for {student_name} on {date.strftime('%d %b %Y')}.\n\n{description}\n\nInsight Institute",
                settings.DEFAULT_FROM_EMAIL,
                [parent_email]
            )
            email.send(fail_silently=True)
        except Exception as e:
            logger.error(f"Failed to send violation email to parent {parent_email}: {e}")


def notify_attendance_correction(student, date, new_status):
    """
    Notify student when their attendance is corrected by admin.
    """
    if not student or not hasattr(student, 'user') or not student.user:
        return

    status_display = new_status.replace('_', ' ').title()
    send_system_notification(
        user_id=str(student.user.id),
        title='Attendance Corrected',
        body=f"Your attendance for {date.strftime('%d %b %Y')} has been corrected to {status_display}.",
        metadata={'module': 'attendance', 'date': str(date), 'status': new_status}
    )


def notify_employee_attendance_marked(emp_user, date, status_val):
    """
    Notify staff member when their attendance is marked by admin.
    (No check-in/check-out event notifications for staff per user request.)
    """
    if not emp_user:
        return

    status_display = status_val.replace('_', ' ').title()
    send_system_notification(
        user_id=str(emp_user.id),
        title='Attendance Marked',
        body=f"Your attendance for {date.strftime('%d %b %Y')} has been marked as {status_display}.",
        metadata={'module': 'attendance', 'date': str(date), 'status': status_val}
    )


def notify_faculty_checkin(faculty_user, scan_type, scan_time, is_late=False, late_minutes=0):
    """
    Notify faculty member on their own check-in / check-out event.
    """
    if not faculty_user:
        return

    action = 'checked in' if scan_type == 'check_in' else 'checked out'
    local_scan_time = timezone.localtime(scan_time) if timezone.is_aware(scan_time) else scan_time
    time_str = local_scan_time.strftime('%I:%M %p')

    if scan_type == 'check_in' and is_late:
        status_label = f'Late ({late_minutes} min late)'
    elif scan_type == 'check_in':
        status_label = 'On Time'
    else:
        status_label = 'Checked Out'

    send_system_notification(
        user_id=str(faculty_user.id),
        title=f'Attendance: {action.title()}',
        body=f"You have {action} at {time_str}. Status: {status_label}.",
        metadata={
            'module': 'attendance',
            'scan_type': scan_type,
            'status': status_label,
            'is_late': is_late,
            'late_minutes': late_minutes,
        }
    )
