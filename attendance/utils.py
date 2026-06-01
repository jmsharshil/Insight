import calendar
from datetime import date, timedelta

from django.db.models import Avg, Count, Q, F
from django.db.models.functions import ExtractHour, ExtractMinute

from .models import AttendanceRecord, ViolationRecord


def compute_attendance_percentage(student_id, month=None, batch_id=None):
    """
    Compute attendance percentage for a student.

    Returns (present_count, total_count, percentage: float).
    present_count = records where status in [present, late, half_day].
    total_count   = all records for the period (excluding on_leave).
    """
    qs = AttendanceRecord.objects.filter(student_id=student_id)

    if batch_id:
        qs = qs.filter(batch_id=batch_id)

    if month:
        try:
            year, mon = map(int, month.split('-'))
            qs = qs.filter(date__year=year, date__month=mon)
        except (ValueError, AttributeError):
            pass  # Ignore malformed month strings

    # Exclude on_leave from total
    qs = qs.exclude(status='on_leave')
    total_count = qs.count()

    # Count present + late + half_day as "present"
    present_count = qs.filter(
        status__in=['present', 'late', 'half_day']
    ).count()

    percentage = round((present_count / total_count) * 100, 2) if total_count > 0 else 0.0

    return present_count, total_count, percentage


def get_batch_attendance_sheet(batch_id, month):
    """
    Build an attendance pivot sheet for a batch.
    Each cell includes status, checked_in_at, and checked_out_at.

    Returns:
        dict: {
            student_id (str): {
                'name': str,
                'roll_number': str,
                'dates': {
                    'YYYY-MM-DD': {
                        'status': str,
                        'checked_in_at': str|None,
                        'checked_out_at': str|None,
                    },
                    ...
                }
            },
            ...
        }
    """
    try:
        year, mon = map(int, month.split('-'))
    except (ValueError, AttributeError):
        return {}

    records = AttendanceRecord.objects.filter(
        batch_id=batch_id,
        date__year=year,
        date__month=mon,
    ).select_related('student').order_by('student', 'date', 'session')

    sheet = {}

    for record in records:
        sid = str(record.student_id)

        if sid not in sheet:
            # Safely extract student info
            try:
                student_name = record.student.user.name if hasattr(record.student, 'user') else str(record.student)
                roll_number = record.student.roll_number if hasattr(record.student, 'roll_number') else ''
            except Exception:
                student_name = str(record.student_id)
                roll_number = ''

            sheet[sid] = {
                'name': student_name,
                'roll_number': roll_number,
                'dates': {},
            }

        date_key = record.date.strftime('%Y-%m-%d')
        checked_in = record.checked_in_at.isoformat() if record.checked_in_at else None
        checked_out = record.checked_out_at.isoformat() if record.checked_out_at else None

        # If multiple sessions on same day, combine them into a list
        existing = sheet[sid]['dates'].get(date_key)
        if existing:
            # Convert single entry to list if needed
            if isinstance(existing, dict):
                existing = [existing]
            existing.append({
                'session': record.session,
                'status': record.status,
                'checked_in_at': checked_in,
                'checked_out_at': checked_out,
            })
            sheet[sid]['dates'][date_key] = existing
        else:
            sheet[sid]['dates'][date_key] = {
                'session': record.session,
                'status': record.status,
                'checked_in_at': checked_in,
                'checked_out_at': checked_out,
            }

    return sheet


def resolve_qr_data(qr_data):
    """
    Accepts roll_number (str) or student UUID.
    Returns Student instance or None.
    """
    from uuid import UUID

    try:
        from students.models import Student
    except Exception:
        return None

    # Try UUID first
    try:
        UUID(str(qr_data))
        return Student.objects.filter(id=qr_data).first()
    except (ValueError, AttributeError):
        pass

    # Try roll_number
    return Student.objects.filter(roll_number=qr_data).first()


def get_active_violations_count(student_id):
    """
    Returns count of unresolved ViolationRecord rows for a student.
    """
    return ViolationRecord.objects.filter(
        student_id=student_id,
        is_resolved=False,
    ).count()


def should_block_qr(student_id):
    """
    Returns True if the student has 3 or more active (unresolved) violations,
    meaning their QR should be temporarily blocked.
    """
    return get_active_violations_count(student_id) >= 3


def get_all_dates_in_month(month_str):
    """
    Return a list of date strings for every day in the given month.

    Args:
        month_str: 'YYYY-MM'

    Returns:
        list[str]: ['2026-01-01', '2026-01-02', ...]
    """
    try:
        year, mon = map(int, month_str.split('-'))
        _, num_days = calendar.monthrange(year, mon)
        return [
            date(year, mon, day).strftime('%Y-%m-%d')
            for day in range(1, num_days + 1)
        ]
    except (ValueError, AttributeError):
        return []


def compute_avg_times(student_id, month=None, batch_id=None):
    """
    Compute average check-in and check-out times for a student.

    Returns:
        tuple: (avg_checkin_time: str|None, avg_checkout_time: str|None)
               Times formatted as 'HH:MM' or None if no data.
    """
    qs = AttendanceRecord.objects.filter(student_id=student_id)

    if batch_id:
        qs = qs.filter(batch_id=batch_id)
    if month:
        try:
            year, mon = map(int, month.split('-'))
            qs = qs.filter(date__year=year, date__month=mon)
        except (ValueError, AttributeError):
            pass

    # Average check-in time
    checkin_qs = qs.filter(checked_in_at__isnull=False).annotate(
        hour=ExtractHour('checked_in_at'),
        minute=ExtractMinute('checked_in_at'),
    ).aggregate(
        avg_hour=Avg('hour'),
        avg_minute=Avg('minute'),
    )

    avg_checkin = None
    if checkin_qs['avg_hour'] is not None:
        h = int(round(checkin_qs['avg_hour']))
        m = int(round(checkin_qs['avg_minute'] or 0))
        avg_checkin = f"{h:02d}:{m:02d}"

    # Average check-out time
    checkout_qs = qs.filter(checked_out_at__isnull=False).annotate(
        hour=ExtractHour('checked_out_at'),
        minute=ExtractMinute('checked_out_at'),
    ).aggregate(
        avg_hour=Avg('hour'),
        avg_minute=Avg('minute'),
    )

    avg_checkout = None
    if checkout_qs['avg_hour'] is not None:
        h = int(round(checkout_qs['avg_hour']))
        m = int(round(checkout_qs['avg_minute'] or 0))
        avg_checkout = f"{h:02d}:{m:02d}"

    return avg_checkin, avg_checkout


def get_violations_breakdown(student_id):
    """
    FRD §4.4.3: Return count per violation type for unresolved violations.
    Returns dict: { violation_type: count }
    """
    from django.db.models import Count
    rows = ViolationRecord.objects.filter(
        student_id=student_id, is_resolved=False,
    ).values('violation_type').annotate(count=Count('id'))

    # Initialize all types to 0
    breakdown = {
        'missing_checkout': 0,
        'no_show': 0,
        'late_entry': 0,
        'missing_checkin_scan': 0,
        'unauthorised_absence': 0,
        'repeated_delay': 0,
    }
    for row in rows:
        breakdown[row['violation_type']] = row['count']
    return breakdown
