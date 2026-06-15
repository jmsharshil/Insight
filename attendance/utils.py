import calendar
import math
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
    ).select_related('student').order_by('student', 'date')

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
                'session': getattr(record, 'session', None),
                'status': record.status,
                'checked_in_at': checked_in,
                'checked_out_at': checked_out,
            })
            sheet[sid]['dates'][date_key] = existing
        else:
            sheet[sid]['dates'][date_key] = {
                'session': getattr(record, 'session', None),
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


def haversine_distance(lat1, lon1, lat2, lon2):
    """
    Calculate the great circle distance between two points 
    on the earth (specified in decimal degrees) in meters.
    """
    # convert decimal degrees to radians 
    lon1, lat1, lon2, lat2 = map(math.radians, [lon1, lat1, lon2, lat2])

    # haversine formula 
    dlon = lon2 - lon1 
    dlat = lat2 - lat1 
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a)) 
    r = 6371 # Radius of earth in kilometers
    return c * r * 1000 # Convert to meters


# E3 ── Location & timing validation ────────────────────────────────────────────

def haversine_distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Pure-Python haversine formula. Returns distance in metres.
    Uses R = 6,371,000 m (mean Earth radius).
    """
    R = 6_371_000  # metres
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2)
    c = 2 * math.asin(math.sqrt(a))
    return R * c


def validate_qr_scan(scan_lat, scan_lng, branch, timetable_slot, scan_time) -> dict:
    """
    Validate a QR scan against branch location and timetable slot window.

    Args:
        scan_lat:      float | None  — student device latitude
        scan_lng:      float | None  — student device longitude
        branch:        branch.Branch instance (must have latitude/longitude/allowed_radius_meters)
        timetable_slot: batches.TimetableSlot | None
        scan_time:     datetime (timezone-aware recommended)

    Returns:
        dict with keys:
            'location_verified': bool | None  (None if coordinates missing)
            'time_verified':     bool | None  (None if slot missing)
            'reason':            str

    Never raises — always returns a dict.
    """
    from datetime import datetime, timedelta
    import pytz

    reasons = []
    location_verified = None
    time_verified = None

    # ─ Location check ─────────────────────────────────────────────────
    if scan_lat is not None and scan_lng is not None:
        branch_lat = branch.latitude
        branch_lng = branch.longitude
        if branch_lat is not None and branch_lng is not None:
            try:
                distance = haversine_distance_meters(
                    float(scan_lat), float(scan_lng),
                    float(branch_lat), float(branch_lng),
                )
                radius = branch.allowed_radius_meters or 100
                if distance <= radius:
                    location_verified = True
                    reasons.append(f"Within {int(distance)}m of branch (radius={radius}m).")
                else:
                    location_verified = False
                    reasons.append(
                        f"Outside radius: {int(distance)}m away (allowed={radius}m)."
                    )
            except Exception as exc:
                reasons.append(f"Location check error: {exc}")
        else:
            reasons.append("Branch has no coordinates configured.")
    else:
        reasons.append("No GPS coordinates provided.")

    # ─ Time check ───────────────────────────────────────────────────
    if timetable_slot is not None:
        try:
            slot_start = timetable_slot.start_time
            slot_end   = timetable_slot.end_time
            if slot_start is not None and slot_end is not None:
                BUFFER = timedelta(minutes=10)

                # Combine scan_time date with slot times
                scan_date = scan_time.date()
                tz = getattr(scan_time, 'tzinfo', None)

                def _combine(t):
                    """Combine date + time(naive), then apply tz if needed."""
                    dt = datetime.combine(scan_date, t)
                    if tz is not None:
                        try:
                            dt = dt.replace(tzinfo=tz)
                        except Exception:
                            pass
                    return dt

                window_start = _combine(slot_start) - BUFFER
                window_end   = _combine(slot_end) + BUFFER

                # Make scan_time offset-naive for comparison if needed
                cmp_scan = scan_time
                if tz is None and hasattr(cmp_scan, 'replace'):
                    cmp_scan = cmp_scan.replace(tzinfo=None)

                if window_start <= cmp_scan <= window_end:
                    time_verified = True
                    reasons.append(
                        f"Scan within window ({slot_start}⊢10min – {slot_end}+10min)."
                    )
                else:
                    time_verified = False
                    reasons.append(
                        f"Outside slot window: scan={scan_time}, "
                        f"window=[{window_start}, {window_end}]."
                    )
            else:
                reasons.append("Slot has no start/end time.")
        except Exception as exc:
            reasons.append(f"Time check error: {exc}")
    else:
        reasons.append("No timetable slot provided.")

    return {
        'location_verified': location_verified,
        'time_verified':     time_verified,
        'reason':            ' | '.join(reasons),
    }
