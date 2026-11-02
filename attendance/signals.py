"""
attendance/signals.py — Cross-module signals for attendance events.

Handles post-attendance actions like violation threshold checks
and low-attendance alerting.
"""

import logging
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(post_save, sender='attendance.ViolationRecord')
def violation_created_or_updated(sender, instance, created, **kwargs):
    """
    When a ViolationRecord is created or resolved,
    trigger the threshold check to potentially block/unblock QR.
    """
    try:
        from attendance.tasks import check_violation_threshold
        check_violation_threshold(str(instance.student_id))
    except Exception as e:
        # Graceful fallback if task is not running correctly
        logger.warning(f"Could not dispatch violation threshold check: {e}")
        try:
            from attendance.utils import should_block_qr
            from students.models import Student
            if should_block_qr(instance.student_id):
                Student.objects.filter(id=instance.student_id).update(qr_blocked=True)
            else:
                Student.objects.filter(id=instance.student_id).update(qr_blocked=False)
        except Exception as inner_e:
            logger.error(f"Fallback violation check failed: {inner_e}")



@receiver(post_save, sender='attendance.EmployeeAttendanceRecord')
@receiver(post_delete, sender='attendance.EmployeeAttendanceRecord')
def sync_payslip_on_employee_attendance_change(sender, instance, **kwargs):
    """
    Automatically recompute and update employee payslip whenever an
    attendance record is created, updated, or deleted.
    """
    try:
        from payroll.utils import sync_payslips_for_attendance_change
        sync_payslips_for_attendance_change(
            user=instance.user,
            target_date=instance.date,
            branch=getattr(instance, 'branch', None) or getattr(instance.user, 'branch', None)
        )
    except Exception as e:
        logger.error(f"[ATTENDANCE SIGNAL] Error syncing payslip for employee {getattr(instance, 'user_id', None)}: {e}")
