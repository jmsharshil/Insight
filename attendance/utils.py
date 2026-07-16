import calendar
import math
from datetime import date, datetime, timedelta

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

    # Use distinct dates to correctly handle multiple sessions/check-ins per day
    # Exclude dates that are purely 'on_leave'
    total_qs = qs.exclude(status='on_leave')
    total_count = total_qs.values('date').distinct().count()

    present_count = total_qs.filter(
        status__in=['present', 'late', 'half_day']
    ).values('date').distinct().count()

    percentage = round((present_count / total_count) * 100, 2) if total_count > 0 else 0.0

    return present_count, total_count, percentage


def get_batch_attendance_sheet(batch_id=None, month=None, branch_id=None):
    """
    Build an attendance pivot sheet for a batch (or all), supporting MULTIPLE
    records/sessions per student per date via timetable_slot.

    Returns:
        dict: {
            student_id (str): {
                'name': str,
                'roll_number': str,
                'branch_name': str,
                'batch_name': str,
                'dates': {
                    'YYYY-MM-DD': {                     # single session
                        'timetable_slot_id': str|None,
                        'slot_code': str|None,
                        'status': str,
                        'checked_in_at': str|None,
                        'checked_out_at': str|None,
                    },
                    OR
                    'YYYY-MM-DD': [                     # multiple sessions
                        { ... }, { ... }
                    ],
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

    from students.models import Student

    student_qs = Student.objects.filter(is_active=True)
    if batch_id:
        student_qs = student_qs.filter(batch_id=batch_id)
    if branch_id:
        student_qs = student_qs.filter(branch_id=branch_id)

    sheet = {}
    for st in student_qs:
        sid = str(st.id)
        sheet[sid] = {
            'name': f"{st.first_name} {st.surname}",
            'roll_number': st.roll_number or '',
            'branch_name': st.branch.name if st.branch else '',
            'batch_name': st.batch.name if st.batch else '',
            'dates': {},
        }

    records = AttendanceRecord.objects.filter(
        date__year=year,
        date__month=mon,
    ).select_related(
        'student', 'student__user', 'student__branch', 'student__batch',
        'timetable_slot'
    )

    if batch_id:
        records = records.filter(student__batch_id=batch_id)
    if branch_id:
        records = records.filter(student__branch_id=branch_id)

    records = records.order_by('student', 'date', 'checked_in_at')

    for record in records:
        sid = str(record.student_id)

        # If student isn't in sheet (e.g., inactive but has records, or we didn't filter strictly above)
        if sid not in sheet:
            try:
                student_name = record.student.user.name if hasattr(record.student, 'user') and record.student.user else str(record.student)
                roll_number = record.student.roll_number if hasattr(record.student, 'roll_number') else ''
                branch_name = record.student.branch.name if hasattr(record.student, 'branch') and record.student.branch else ''
                batch_name = record.student.batch.name if hasattr(record.student, 'batch') and record.student.batch else ''
            except Exception:
                student_name = str(record.student_id)
                roll_number = ''
                branch_name = ''
                batch_name = ''

            sheet[sid] = {
                'name': student_name,
                'roll_number': roll_number,
                'branch_name': branch_name,
                'batch_name': batch_name,
                'dates': {},
            }

        date_key = record.date.strftime('%Y-%m-%d')
        checked_in = record.checked_in_at.isoformat() if record.checked_in_at else None
        checked_out = record.checked_out_at.isoformat() if record.checked_out_at else None
        slot_id = str(record.timetable_slot_id) if record.timetable_slot_id else None
        slot_code = record.timetable_slot.slot_code if record.timetable_slot and hasattr(record.timetable_slot, 'slot_code') else None

        session_info = {
            'timetable_slot_id': slot_id,
            'slot_code': slot_code,
            'status': record.status,
            'checked_in_at': checked_in,
            'checked_out_at': checked_out,
        }

        # If multiple sessions on same day (now supported), combine them into a list.
        # Normalize legacy dicts (had 'session' key) to new structure for consistency.
        existing = sheet[sid]['dates'].get(date_key)
        if existing:
            if isinstance(existing, dict):
                # Convert previous single-entry dict (possibly legacy 'session' key)
                if 'session' in existing and 'timetable_slot_id' not in existing:
                    legacy_session = existing.pop('session', None)
                    existing['timetable_slot_id'] = legacy_session
                    existing['slot_code'] = None
                existing = [existing]
            existing.append(session_info)
            sheet[sid]['dates'][date_key] = existing
        else:
            sheet[sid]['dates'][date_key] = session_info

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
    """Returns True if QR/attendance check-in should be blocked (violations or overdue fees)."""
    return get_qr_block_reason(student_id) is not None


def get_qr_block_reason(student_id):
    """
    Returns reason string ('violations' or 'overdue_fees') or None if not blocked.
    Used by QRScanView to give specific user messages.
    """
    if get_active_violations_count(student_id) >= 3:
        return 'violations'

    # Check for fee overdue (>15 days past installment due_date)
    try:
        from fees.utils import has_overdue_installment
        if has_overdue_installment(student_id):
            return 'overdue_fees'
    except Exception:
        # Graceful fallback (fees app unavailable)
        pass

    return None


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


def get_attendance_buffer_minutes(timetable_slot, scan_time, is_first_class_of_day=False):
    """Return the allowed grace window in minutes for a check-in scan."""
    if is_first_class_of_day:
        return 15
    return 5


def get_attendance_entry_status(timetable_slot, scan_time, is_first_class_of_day=False):
    """Return 'on_time' or 'late_entry' based on the configured grace buffer."""
    if timetable_slot is None:
        return 'on_time'

    start_time = getattr(timetable_slot, 'start_time', None)
    if start_time is None:
        return 'on_time'

    buffer_minutes = get_attendance_buffer_minutes(timetable_slot, scan_time, is_first_class_of_day=is_first_class_of_day)
    scan_dt = scan_time
    if hasattr(scan_dt, 'date'):
        scan_dt = datetime.combine(scan_dt.date(), scan_dt.time())

    slot_dt = datetime.combine(scan_dt.date(), start_time)
    if scan_dt <= slot_dt + timedelta(minutes=buffer_minutes):
        return 'on_time'
    return 'late_entry'


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
                BUFFER = timedelta(minutes=45)

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

                window_start = _combine(slot_start) - timedelta(minutes=15)
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
