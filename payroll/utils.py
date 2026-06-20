import logging
import calendar
from decimal import Decimal
from datetime import datetime, timedelta
from collections import defaultdict
from django.utils import timezone

logger = logging.getLogger(__name__)


def get_subject_hourly_rate(faculty_profile, subject, month, year):
    """
    NEW (FRD §4.8.4): returns the effective hourly rate for a given faculty+subject.
    -> Query SubjectHourlyRate for (faculty, subject) where
       effective_from <= last day of payroll month
    -> Return latest record's hourly_rate
    -> If no record: return faculty_profile.hourly_rate (default fallback)
    """
    from faculty.models import SubjectHourlyRate

    last_day = calendar.monthrange(year, month)[1]
    from datetime import date
    month_end = date(year, month, last_day)

    rate_record = SubjectHourlyRate.objects.filter(
        faculty=faculty_profile,
        subject=subject,
        effective_from__lte=month_end,
    ).order_by('-effective_from').first()

    if rate_record:
        return rate_record.hourly_rate
    return faculty_profile.hourly_rate


def compute_payslip_for_faculty(faculty_profile, month, year, payroll_run):
    """
    FRD §4.8.4 — Hour-Based Payroll Computation.
    Reconciles SessionReport hours with QR attendance hours.
    """
    from .models import PaySlip, SessionLatePenaltyLog, LateEntryPolicy
    from faculty.models import SessionReport, FacultyQRScanLog
    from leave.models import LeaveApplication

    # 1. Fetch session reports
    sessions = SessionReport.objects.filter(
        faculty=faculty_profile,
        session_date__year=year,
        session_date__month=month,
    ).select_related('subject')

    # 2. Compute session hours and hour_based_amount per subject
    session_dates = set()
    subject_hours = defaultdict(Decimal)
    total_session_minutes = Decimal(0)

    for s in sessions:
        session_dates.add(s.session_date)
        hours = Decimal(s.duration_minutes) / Decimal(60)
        subject_hours[s.subject_id] += hours
        total_session_minutes += Decimal(s.duration_minutes)

    # 3. QR attendance hours for dates WITHOUT session reports
    qr_logs = FacultyQRScanLog.objects.filter(
        faculty=faculty_profile,
        scanned_at__year=year,
        scanned_at__month=month,
    ).order_by('scanned_at')

    # Group QR logs by date
    qr_by_date = defaultdict(list)
    for log in qr_logs:
        qr_by_date[log.scanned_at.date()].append(log)

    qr_extra_minutes = Decimal(0)
    for log_date, logs in qr_by_date.items():
        if log_date in session_dates:
            continue  # SessionReport hours already counted for this date
        check_ins = [l for l in logs if l.scan_type == 'check_in']
        check_outs = [l for l in logs if l.scan_type == 'check_out']
        if check_ins and check_outs:
            first_in = min(l.scanned_at for l in check_ins)
            last_out = max(l.scanned_at for l in check_outs)
            diff_minutes = Decimal((last_out - first_in).total_seconds()) / Decimal(60)
            qr_extra_minutes += max(diff_minutes, Decimal(0))

    total_hours = (total_session_minutes + qr_extra_minutes) / Decimal(60)

    # 4. Compute hour_based_amount per subject
    hour_based_amount = Decimal(0)
    for subject_id, hours in subject_hours.items():
        from batches.models import Subject
        try:
            subject = Subject.objects.get(id=subject_id)
        except Subject.DoesNotExist:
            subject = None
        rate = get_subject_hourly_rate(faculty_profile, subject, month, year) if subject else faculty_profile.hourly_rate
        hour_based_amount += hours * rate

    # Add QR-only hours at default rate
    qr_extra_hours = qr_extra_minutes / Decimal(60)
    hour_based_amount += qr_extra_hours * faculty_profile.hourly_rate

    sessions_count = sessions.count()

    # 5. Late penalty computation
    late_penalty = Decimal(0)
    policy = LateEntryPolicy.objects.filter(branch=faculty_profile.branch, is_active=True).first()

    # 6. Leave deductions
    approved_leaves = LeaveApplication.objects.filter(
        applied_by=faculty_profile.user,
        status='approved',
        from_date__year=year,
        from_date__month=month,
        leave_type='unpaid',
    )
    leave_days = sum(l.total_days for l in approved_leaves)
    daily_rate = faculty_profile.salary / Decimal(30) if faculty_profile.salary else Decimal(0)
    leave_deductions = Decimal(leave_days) * daily_rate

    # 7. Working days
    working_days = sum(1 for d in range(1, calendar.monthrange(year, month)[1] + 1)
                       if calendar.weekday(year, month, d) < 5)

    # 8. Absence deductions
    days_with_attendance = len(session_dates | set(qr_by_date.keys()))
    absent_days = max(0, working_days - days_with_attendance)
    absence_deduction_rate = policy.absence_deduction_per_day if policy else Decimal(0)
    absence_deductions = Decimal(absent_days) * absence_deduction_rate

    # 9. Compute net salary
    if faculty_profile.employment_type == 'full_time':
        basic_salary = faculty_profile.salary
        applied_hour_based_amount = Decimal(0)
        applied_leave_deductions = leave_deductions
        net = (basic_salary - late_penalty - absence_deductions
               - applied_leave_deductions)
    else:
        basic_salary = Decimal(0)
        applied_hour_based_amount = hour_based_amount
        applied_leave_deductions = Decimal(0)
        net = applied_hour_based_amount - late_penalty - absence_deductions

    net = max(net, Decimal(0))

    # 10. Create PaySlip
    payslip = PaySlip.objects.create(
        payroll_run=payroll_run,
        faculty=faculty_profile,
        basic_salary=basic_salary,
        total_session_hours=total_hours,
        hour_based_amount=applied_hour_based_amount,
        late_penalty=late_penalty,
        absence_deductions=absence_deductions,
        leave_deductions=applied_leave_deductions,
        net_salary=net,
        leaves_taken=int(leave_days),
        working_days=working_days,
        sessions_conducted=sessions_count,
    )

    # 11. Late penalty logs (per session)
    if policy:
        for s in sessions:
            grace = policy.grace_period_minutes
            # Compare start_time with batch session_start_time as scheduled time
            from batches.models import TimetableSlot
            scheduled_time = s.start_time  # default fallback
            dow = s.session_date.weekday()
            slot = TimetableSlot.objects.filter(batch_id=s.batch_id, subject_id=s.subject_id, day_of_week=dow).first()
            if slot and slot.start_time:
                scheduled_time = slot.start_time

            sched_dt = datetime.combine(datetime.today(), scheduled_time)
            actual_dt = datetime.combine(datetime.today(), s.start_time)
            diff = (actual_dt - sched_dt).total_seconds() / 60

            if diff > grace:
                late_min = int(diff - grace)
                penalty = min(
                    Decimal(late_min) * policy.deduction_per_minute,
                    policy.max_deduction_per_session if policy.max_deduction_per_session > 0
                    else Decimal('999999'),
                )
                SessionLatePenaltyLog.objects.create(
                    payslip=payslip,
                    session_report=s,
                    scheduled_time=scheduled_time,
                    actual_start=s.start_time,
                    late_minutes=late_min,
                    penalty_amount=penalty,
                    grace_applied=False,
                )
                late_penalty += penalty
            elif diff > 0:
                SessionLatePenaltyLog.objects.create(
                    payslip=payslip,
                    session_report=s,
                    scheduled_time=scheduled_time,
                    actual_start=s.start_time,
                    late_minutes=int(diff),
                    penalty_amount=Decimal(0),
                    grace_applied=True,
                )

        # Update payslip with computed late penalty
        if late_penalty > 0:
            payslip.late_penalty = late_penalty
            if faculty_profile.employment_type == 'full_time':
                payslip.net_salary = max(
                    basic_salary - late_penalty - absence_deductions
                    - applied_leave_deductions, Decimal(0)
                )
            else:
                payslip.net_salary = max(
                    applied_hour_based_amount - late_penalty - absence_deductions, Decimal(0)
                )
            payslip.save(update_fields=['late_penalty', 'net_salary'])

    return payslip


def generate_employee_id(branch_code):
    """
    Auto-generate unique employee ID: EMP-{BRANCH_CODE}-{padded_4_digit_seq}
    Example: EMP-BRN-0001
    """
    from faculty.models import FacultyProfile
    if hasattr(branch_code, 'code'):
        code = branch_code.code
        branch = branch_code
    else:
        code = str(branch_code)[:4].upper()
        branch = None

    if branch:
        count = FacultyProfile.objects.filter(branch=branch).count() + 1
    else:
        count = FacultyProfile.objects.count() + 1

    return f"EMP-{code}-{str(count).zfill(4)}"


def preview_payslip_for_faculty(faculty_profile, month, year):
    """
    Computes and returns a preview of the payslip calculation for a given month/year
    without creating any database records.
    """
    from .models import LateEntryPolicy
    from faculty.models import SessionReport, FacultyQRScanLog
    from leave.models import LeaveApplication

    sessions = SessionReport.objects.filter(
        faculty=faculty_profile,
        session_date__year=year,
        session_date__month=month,
    ).select_related('subject')

    session_dates = set()
    subject_hours = defaultdict(Decimal)
    total_session_minutes = Decimal(0)

    for s in sessions:
        session_dates.add(s.session_date)
        hours = Decimal(s.duration_minutes) / Decimal(60)
        subject_hours[s.subject_id] += hours
        total_session_minutes += Decimal(s.duration_minutes)

    qr_logs = FacultyQRScanLog.objects.filter(
        faculty=faculty_profile,
        scanned_at__year=year,
        scanned_at__month=month,
    ).order_by('scanned_at')

    qr_by_date = defaultdict(list)
    for log in qr_logs:
        qr_by_date[log.scanned_at.date()].append(log)

    qr_extra_minutes = Decimal(0)
    for log_date, logs in qr_by_date.items():
        if log_date in session_dates:
            continue
        check_ins = [l for l in logs if l.scan_type == 'check_in']
        check_outs = [l for l in logs if l.scan_type == 'check_out']
        if check_ins and check_outs:
            first_in = min(l.scanned_at for l in check_ins)
            last_out = max(l.scanned_at for l in check_outs)
            diff_minutes = Decimal((last_out - first_in).total_seconds()) / Decimal(60)
            qr_extra_minutes += max(diff_minutes, Decimal(0))

    total_hours = (total_session_minutes + qr_extra_minutes) / Decimal(60)

    hour_based_amount = Decimal(0)
    for subject_id, hours in subject_hours.items():
        from batches.models import Subject
        try:
            subject = Subject.objects.get(id=subject_id)
        except Subject.DoesNotExist:
            subject = None
        rate = get_subject_hourly_rate(faculty_profile, subject, month, year) if subject else faculty_profile.hourly_rate
        hour_based_amount += hours * rate

    qr_extra_hours = qr_extra_minutes / Decimal(60)
    hour_based_amount += qr_extra_hours * faculty_profile.hourly_rate

    sessions_count = sessions.count()

    late_penalty = Decimal(0)
    policy = LateEntryPolicy.objects.filter(branch=faculty_profile.branch, is_active=True).first()

    approved_leaves = LeaveApplication.objects.filter(
        applied_by=faculty_profile.user,
        status='approved',
        from_date__year=year,
        from_date__month=month,
        leave_type='unpaid',
    )
    leave_days = sum(l.total_days for l in approved_leaves)
    daily_rate = faculty_profile.salary / Decimal(30) if faculty_profile.salary else Decimal(0)
    leave_deductions = Decimal(leave_days) * daily_rate

    working_days = sum(1 for d in range(1, calendar.monthrange(year, month)[1] + 1)
                       if calendar.weekday(year, month, d) < 5)

    days_with_attendance = len(session_dates | set(qr_by_date.keys()))
    absent_days = max(0, working_days - days_with_attendance)
    absence_deduction_rate = policy.absence_deduction_per_day if policy else Decimal(0)
    absence_deductions = Decimal(absent_days) * absence_deduction_rate

    if policy:
        for s in sessions:
            grace = policy.grace_period_minutes
            from batches.models import TimetableSlot
            scheduled_time = s.start_time
            dow = s.session_date.weekday()
            slot = TimetableSlot.objects.filter(batch_id=s.batch_id, subject_id=s.subject_id, day_of_week=dow).first()
            if slot and slot.start_time:
                scheduled_time = slot.start_time

            sched_dt = datetime.combine(datetime.today(), scheduled_time)
            actual_dt = datetime.combine(datetime.today(), s.start_time)
            diff = (actual_dt - sched_dt).total_seconds() / 60

            if diff > grace:
                late_min = int(diff - grace)
                penalty = min(
                    Decimal(late_min) * policy.deduction_per_minute,
                    policy.max_deduction_per_session if policy.max_deduction_per_session > 0
                    else Decimal('999999'),
                )
                late_penalty += penalty

    if faculty_profile.employment_type == 'full_time':
        basic_salary = faculty_profile.salary
        applied_hour_based_amount = Decimal(0)
        applied_leave_deductions = leave_deductions
        net = (basic_salary - late_penalty - absence_deductions
               - applied_leave_deductions)
    else:
        basic_salary = Decimal(0)
        applied_hour_based_amount = hour_based_amount
        applied_leave_deductions = Decimal(0)
        net = applied_hour_based_amount - late_penalty - absence_deductions

    net = max(net, Decimal(0))

    return {
        'basic_salary': str(basic_salary),
        'total_session_hours': str(round(total_hours, 2)),
        'hour_based_amount': str(round(applied_hour_based_amount, 2)),
        'late_penalty': str(round(late_penalty, 2)),
        'absence_deductions': str(round(absence_deductions, 2)),
        'leave_deductions': str(round(applied_leave_deductions, 2)),
        'bonus': "0.00",
        'other_deductions': "0.00",
        'net_salary': str(round(net, 2)),
        'leaves_taken': int(leave_days),
        'working_days': working_days,
        'sessions_conducted': sessions_count,
    }

