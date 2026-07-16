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
    if faculty_profile.hourly_rate > 0:
        return faculty_profile.hourly_rate
    return faculty_profile.user.hourly_rate


def compute_payslip_for_faculty(faculty_profile, month, year, payroll_run):
    fac_hourly_rate = faculty_profile.hourly_rate if faculty_profile.hourly_rate > 0 else faculty_profile.user.hourly_rate
    fac_session_hours = faculty_profile.session_hours if faculty_profile.session_hours > 0 else faculty_profile.user.session_hours
    fac_salary = faculty_profile.salary if faculty_profile.salary > 0 else faculty_profile.user.salary
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

    session_dates = set()
    subject_hours = defaultdict(Decimal)
    total_session_minutes = Decimal(0)
    
    chapter_monthly_minutes = defaultdict(Decimal)
    daily_stats = defaultdict(lambda: {'total_hours': Decimal(0), 'gross_salary': Decimal(0), 'deduction': Decimal(0), 'late_minutes': 0, 'penalty_minutes': 0})

    for s in sessions:
        session_dates.add(s.session_date)
        
        # Calculate scheduled duration
        from batches.models import TimetableSlot
        from django.db.models import Q
        dow = s.session_date.weekday()
        slot = TimetableSlot.objects.filter(
            Q(day_of_week=dow) | Q(session_date=s.session_date),
            batch_id=s.batch_id, subject_id=s.subject_id
        ).first()
        
        scheduled_minutes = Decimal(s.duration_minutes)
        if slot and slot.start_time and slot.end_time:
            s_dt = datetime.combine(s.session_date, slot.start_time)
            e_dt = datetime.combine(s.session_date, slot.end_time)
            if e_dt < s_dt:
                e_dt += timedelta(days=1)
            scheduled_minutes = Decimal((e_dt - s_dt).total_seconds()) / Decimal(60)
            
        actual_minutes = Decimal(s.duration_minutes)
        if scheduled_minutes > 0:
            actual_minutes = min(actual_minutes, scheduled_minutes)
            
        chapters = list(s.chapters.all())
        if chapters:
            mins_per_chap = actual_minutes / len(chapters)
            for c in chapters:
                chapter_monthly_minutes[c] += mins_per_chap
        else:
            hours = actual_minutes / Decimal(60)
            subject_hours[s.subject_id] += hours
            total_session_minutes += actual_minutes

        d_str = s.session_date.strftime('%Y-%m-%d')
        daily_stats[d_str]['total_hours'] += actual_minutes / Decimal(60)
        rate = get_subject_hourly_rate(faculty_profile, s.subject, month, year) if hasattr(s, 'subject') and s.subject else fac_hourly_rate
        daily_stats[d_str]['gross_salary'] += (actual_minutes / Decimal(60)) * rate

    from payroll.models import ExtraHoursApproval
    from datetime import date
    first_of_month = date(year, month, 1)

    for chap, monthly_mins in chapter_monthly_minutes.items():
        prev_reports = SessionReport.objects.filter(
            faculty=faculty_profile,
            chapters=chap,
            session_date__lt=first_of_month
        ).distinct()
        
        prev_mins = Decimal(0)
        for pr in prev_reports:
            pr_chapters_count = pr.chapters.count()
            if pr_chapters_count > 0:
                prev_mins += Decimal(pr.duration_minutes) / pr_chapters_count

        allocated_mins = Decimal(chap.duration_hours * 60)
        remaining_allocated_mins = max(allocated_mins - prev_mins, Decimal(0))
        
        payable_mins = monthly_mins
        extra_mins = Decimal(0)
        
        if monthly_mins > remaining_allocated_mins:
            payable_mins = remaining_allocated_mins
            extra_mins = monthly_mins - remaining_allocated_mins
            
            approval, _ = ExtraHoursApproval.objects.get_or_create(
                faculty=faculty_profile,
                chapter=chap,
                payroll_month=month,
                payroll_year=year,
                defaults={'extra_minutes': int(extra_mins)}
            )
            
            if approval.status == 'pending' and approval.extra_minutes != int(extra_mins):
                approval.extra_minutes = int(extra_mins)
                approval.save(update_fields=['extra_minutes'])
                
            if approval.status == 'approved':
                payable_mins += Decimal(approval.extra_minutes)

        hours = payable_mins / Decimal(60)
        subject_hours[chap.subject_id] += hours
        total_session_minutes += payable_mins

    # 3. QR attendance hours for dates WITHOUT session reports
    qr_logs = FacultyQRScanLog.objects.filter(
        faculty=faculty_profile,
        scanned_at__year=year,
        scanned_at__month=month,
    ).order_by('scanned_at')

    # Group QR logs by LOCAL date (not UTC) to avoid date crossing at midnight IST
    from django.utils import timezone as dj_timezone
    qr_by_date = defaultdict(list)
    for log in qr_logs:
        local_scanned = dj_timezone.localtime(log.scanned_at)
        qr_by_date[local_scanned.date()].append(log)

    qr_extra_minutes = Decimal(0)
    # Also track per-slot check-in/out for buffer deduction computation
    qr_slot_deviation = defaultdict(lambda: {'late_in': Decimal(0), 'early_out': Decimal(0)})

    for log_date, logs in qr_by_date.items():
        if log_date in session_dates:
            continue  # SessionReport hours already counted for this date
        check_ins = [l for l in logs if l.scan_type == 'check_in']
        check_outs = [l for l in logs if l.scan_type == 'check_out']
        if check_ins and check_outs:
            # Use local times for all calculations
            first_in_local = dj_timezone.localtime(min(l.scanned_at for l in check_ins))
            last_out_local = dj_timezone.localtime(max(l.scanned_at for l in check_outs))
            actual_in_time = first_in_local.time()
            actual_out_time = last_out_local.time()
            diff_minutes = Decimal((last_out_local - first_in_local).total_seconds()) / Decimal(60)

            # Find scheduled slots for this date to cap hours and compute buffer deviation
            from batches.models import TimetableSlot
            from django.db.models import Q
            dow = log_date.weekday()
            slots = TimetableSlot.objects.filter(
                Q(day_of_week=dow) | Q(session_date=log_date),
                faculty=faculty_profile,
            )
            scheduled_minutes = Decimal(0)
            for slot in slots:
                if slot.start_time and slot.end_time:
                    s_dt = datetime.combine(log_date, slot.start_time)
                    e_dt = datetime.combine(log_date, slot.end_time)
                    if e_dt < s_dt:
                        e_dt += timedelta(days=1)
                    scheduled_minutes += Decimal((e_dt - s_dt).total_seconds()) / Decimal(60)

                    # Compute late check-in and early check-out deviation per slot
                    actual_in_dt = datetime.combine(log_date, actual_in_time)
                    actual_out_dt = datetime.combine(log_date, actual_out_time)
                    late_in = max(Decimal(0), Decimal((actual_in_dt - s_dt).total_seconds()) / Decimal(60))
                    early_out = max(Decimal(0), Decimal((e_dt - actual_out_dt).total_seconds()) / Decimal(60))
                    d_str = log_date.strftime('%Y-%m-%d')
                    qr_slot_deviation[d_str]['late_in'] += late_in
                    qr_slot_deviation[d_str]['early_out'] += early_out

            if scheduled_minutes > 0:
                diff_minutes = min(diff_minutes, scheduled_minutes)

            qr_extra_minutes += max(diff_minutes, Decimal(0))

            if diff_minutes > 0:
                d_str = log_date.strftime('%Y-%m-%d')
                daily_stats[d_str]['total_hours'] += diff_minutes / Decimal(60)
                daily_stats[d_str]['gross_salary'] += (diff_minutes / Decimal(60)) * fac_hourly_rate

    # total_hours: only actual hours worked (no guaranteed base session_hours inflation)
    total_hours = (total_session_minutes + qr_extra_minutes) / Decimal(60)

    # 4. Compute hour_based_amount per subject
    hour_based_amount = Decimal(0)
    for subject_id, hours in subject_hours.items():
        from batches.models import Subject
        try:
            subject = Subject.objects.get(id=subject_id)
        except Subject.DoesNotExist:
            subject = None
        rate = get_subject_hourly_rate(faculty_profile, subject, month, year) if subject else fac_hourly_rate
        hour_based_amount += hours * rate

    # Add QR-only hours at default rate (no base session_hours inflation for visiting/part-time)
    qr_extra_hours = qr_extra_minutes / Decimal(60)
    hour_based_amount += qr_extra_hours * fac_hourly_rate
    # NOTE: fac_session_hours is NOT added here. For visiting faculty, only actual worked hours
    # are paid. session_hours on profile is just a reference/default, not a guaranteed minimum.

    sessions_count = sessions.count()

    # 5. Late penalty computation
    late_penalty = Decimal(0)
    policy = LateEntryPolicy.objects.filter(branch=faculty_profile.branch, is_active=True).first()
    
    # Calculate implicit deduction per minute based on salary/hourly_rate
    if faculty_profile.employment_type == 'full_time':
        # Net salary after retention — deductions are calculated from this
        retention_pct = faculty_profile.salary_retention_percentage or Decimal(0)
        effective_salary = fac_salary * (1 - retention_pct / Decimal(100)) if fac_salary else Decimal(0)
        
        if faculty_profile.work_start_time and faculty_profile.work_end_time:
            s_dt = datetime.combine(datetime.today(), faculty_profile.work_start_time)
            e_dt = datetime.combine(datetime.today(), faculty_profile.work_end_time)
            if e_dt < s_dt:
                e_dt += timedelta(days=1)
            work_mins = Decimal((e_dt - s_dt).total_seconds()) / Decimal(60)
            if work_mins > 0:
                implicit_deduction_per_minute = (effective_salary / Decimal(30)) / work_mins
            else:
                implicit_deduction_per_minute = (effective_salary / Decimal(30)) / Decimal(8) / Decimal(60) if effective_salary else Decimal(0)
        else:
            implicit_deduction_per_minute = (effective_salary / Decimal(30)) / Decimal(8) / Decimal(60) if effective_salary else Decimal(0)
    else:
        # Hourly rate is the effective take-home rate for part-time/visiting
        implicit_deduction_per_minute = fac_hourly_rate / Decimal(60) if fac_hourly_rate else Decimal(0)
        
    deduction_rate = policy.deduction_per_minute if policy and policy.deduction_per_minute > 0 else implicit_deduction_per_minute
    grace = policy.grace_period_minutes if policy else 5
    max_deduction = policy.max_deduction_per_session if policy and policy.max_deduction_per_session > 0 else Decimal('999999')
    
    # 5. Build late penalty data
    #
    # For visiting/part-time faculty:
    #   The 5-minute COMBINED buffer applies per slot:
    #     total_deviation = late_check_in_minutes + early_checkout_minutes
    #     if total_deviation <= 5: no deduction
    #     else: deduct (total_deviation - 5) * per_minute_rate
    #
    # For full_time faculty:
    #   Legacy approach: separate late_in + early_out tracked in daily_delays.

    session_late_details = []
    daily_delays = defaultdict(int)  # Used for full_time and log audit

    for s in sessions:
        from batches.models import TimetableSlot
        scheduled_time = s.start_time
        scheduled_end_time = s.end_time
        dow = s.session_date.weekday()
        slot = TimetableSlot.objects.filter(batch_id=s.batch_id, subject_id=s.subject_id, day_of_week=dow).first()
        if slot and slot.start_time:
            scheduled_time = slot.start_time
        if slot and slot.end_time:
            scheduled_end_time = slot.end_time

        sched_dt = datetime.combine(s.session_date, scheduled_time)
        actual_dt = datetime.combine(s.session_date, s.start_time)
        diff = (actual_dt - sched_dt).total_seconds() / 60

        sched_end_dt = datetime.combine(s.session_date, scheduled_end_time)
        actual_end_dt = datetime.combine(s.session_date, s.end_time)
        if sched_end_dt < sched_dt:
            sched_end_dt += timedelta(days=1)
        if actual_end_dt < actual_dt:
            actual_end_dt += timedelta(days=1)
        diff_end = (sched_end_dt - actual_end_dt).total_seconds() / 60

        late_in_min = max(0, int(diff))
        early_out_min = max(0, int(diff_end))
        total_session_diff = late_in_min + early_out_min

        if total_session_diff > 0:
            daily_delays[s.session_date] += total_session_diff
            session_late_details.append({
                'session': s,
                'scheduled_time': scheduled_time,
                'actual_start': s.start_time,
                'late_minutes': total_session_diff,
                'grace_applied': (total_session_diff <= grace)
            })

    # Compute total late penalty
    late_penalty = Decimal(0)
    late_half_days = 0
    days_late_15_mins = 0
    late_dates = []
    half_day_dates = []
    total_late_penalty_minutes = 0

    if faculty_profile.employment_type in ('visiting', 'part_time', 'contract'):
        # ── Visiting/Part-time: 5-minute COMBINED buffer per slot ──────────────────
        # Session-based deviation
        for d_date, d_delay in daily_delays.items():
            d_str = d_date.strftime('%Y-%m-%d')
            daily_stats[d_str]['late_minutes'] = d_delay
            # Apply 5-minute buffer: only penalize minutes BEYOND 5
            if d_delay > grace:
                penalty_min = d_delay - grace
                day_penalty = min(Decimal(penalty_min) * deduction_rate, max_deduction)
                late_penalty += day_penalty
                total_late_penalty_minutes += penalty_min
                late_dates.append(d_str)
                daily_stats[d_str]['penalty_minutes'] = penalty_min
                daily_stats[d_str]['deduction'] += day_penalty

        # QR-based deviation (dates without session reports)
        for d_str, deviation in qr_slot_deviation.items():
            total_dev = deviation['late_in'] + deviation['early_out']
            d_date = datetime.strptime(d_str, '%Y-%m-%d').date()
            daily_stats[d_str]['late_minutes'] = int(total_dev)
            if total_dev > Decimal(grace):
                penalty_min = int(total_dev - Decimal(grace))
                day_penalty = min(Decimal(penalty_min) * deduction_rate, max_deduction)
                late_penalty += day_penalty
                total_late_penalty_minutes += penalty_min
                if d_str not in late_dates:
                    late_dates.append(d_str)
                daily_stats[d_str]['penalty_minutes'] = penalty_min
                daily_stats[d_str]['deduction'] += day_penalty
    else:
        # ── Full-time: legacy approach — aggregate daily delays ─────────────────────
        for log_date, logs in qr_by_date.items():
            for log in logs:
                daily_delays[log_date] += log.late_minutes
                daily_delays[log_date] += log.early_minutes

        for d_date, d_delay in daily_delays.items():
            if d_date.weekday() == 6:
                continue

            d_str = d_date.strftime('%Y-%m-%d')
            daily_stats[d_str]['late_minutes'] = d_delay

            if d_delay >= 60:
                late_half_days += 1
                half_day_dates.append(d_str)
            else:
                if d_delay >= 15:
                    days_late_15_mins += 1

                if d_delay > grace:
                    penalty_min = d_delay - grace
                    day_penalty = min(Decimal(penalty_min) * deduction_rate, max_deduction)
                    late_penalty += day_penalty
                    total_late_penalty_minutes += penalty_min
                    late_dates.append(d_str)
                    daily_stats[d_str]['penalty_minutes'] = penalty_min
                    daily_stats[d_str]['deduction'] += day_penalty

    per_day_deduction_log = []
    for d_str, stat in sorted(daily_stats.items()):
        net_salary = max(Decimal(0), stat['gross_salary'] - stat['deduction'])
        per_day_deduction_log.append({
            'date': d_str,
            'total_hours': str(round(stat['total_hours'], 2)),
            'gross_salary': str(round(stat['gross_salary'], 2)),
            'deduction': str(round(stat['deduction'], 2)),
            'net_salary': str(round(net_salary, 2)),
            'late_minutes': stat['late_minutes'],
            'penalty_minutes': stat['penalty_minutes'],
            'penalty_amount': str(round(stat['deduction'], 2)),
        })

    late_half_days += (days_late_15_mins // 3)

    # 6. Leave deductions
    approved_leaves = LeaveApplication.objects.filter(
        applied_by=faculty_profile.user,
        status='approved',
        from_date__year=year,
        from_date__month=month,
        leave_type='unpaid',
    )
    leave_days = sum(l.total_days for l in approved_leaves)
    leave_dates = []
    for l in approved_leaves:
        leave_dates.append(f"{l.from_date.strftime('%Y-%m-%d')} to {l.to_date.strftime('%Y-%m-%d')}")
    if fac_hourly_rate != Decimal(0):
        daily_rate = Decimal(0)
    else:
        daily_rate = fac_salary / Decimal(30) if fac_salary else Decimal(0)
    leave_deductions = Decimal(leave_days) * daily_rate

    # 7. Working days
    working_days = sum(1 for d in range(1, calendar.monthrange(year, month)[1] + 1)
                       if calendar.weekday(year, month, d) < 5)

    # 8. Absence deductions
    # Sundays that have any QR/session attendance count as full day present
    days_with_attendance = len(session_dates | set(qr_by_date.keys()))
    attended_dates = session_dates | set(qr_by_date.keys())
    absent_dates = []
    from datetime import date
    today = date.today()
    if year < today.year or (year == today.year and month < today.month):
        working_days_passed = working_days
        last_day = calendar.monthrange(year, month)[1]
    elif year == today.year and month == today.month:
        last_day = min(today.day, calendar.monthrange(year, month)[1])
        working_days_passed = sum(1 for d in range(1, last_day + 1) if calendar.weekday(year, month, d) < 5)
    else:
        working_days_passed = 0
        last_day = 0
        
    absent_days = Decimal(max(0, working_days_passed - days_with_attendance))
    
    for d in range(1, last_day + 1):
        if calendar.weekday(year, month, d) < 5:
            curr_date = date(year, month, d)
            if curr_date not in attended_dates:
                absent_dates.append(curr_date.strftime('%Y-%m-%d'))

    
    # Add late half days
    absent_days += Decimal(late_half_days) * Decimal('0.5')
    
    absence_deduction_rate = policy.absence_deduction_per_day if policy and policy.absence_deduction_per_day > 0 else daily_rate
    absence_deductions = absent_days * absence_deduction_rate

    # 8.5 Attendance Bonus & Salary Retention
    attendance_bonus = Decimal(0)
    if working_days > 0:
        attendance_percentage = (Decimal(days_with_attendance) / Decimal(working_days)) * 100
        if attendance_percentage > Decimal(80):
            attendance_bonus = daily_rate

    basic_salary = fac_salary if faculty_profile.employment_type == 'full_time' else Decimal(0)
    retention_deduction = Decimal(0)
    if faculty_profile.salary_retention_percentage > 0:
        gross_salary = basic_salary + hour_based_amount
        retention_deduction = gross_salary * (faculty_profile.salary_retention_percentage / Decimal(100))

    leave_encashment = Decimal(0)
    if month == 3:
        from leave.models import LeaveBalance
        balances = LeaveBalance.objects.filter(user=faculty_profile.user, year=year - 1)
        for bal in balances:
            if bal.remaining_days > Decimal(0):
                leave_encashment += bal.remaining_days * daily_rate
                # Ensure it's not carried forward
                bal.used_days += bal.remaining_days
                bal.save(update_fields=['used_days'])

    # 9. Compute net salary
    if faculty_profile.employment_type == 'full_time':
        applied_hour_based_amount = hour_based_amount
        applied_leave_deductions = leave_deductions
        net = (basic_salary + applied_hour_based_amount + attendance_bonus + leave_encashment
               - late_penalty - absence_deductions
               - applied_leave_deductions - retention_deduction)
    else:
        applied_hour_based_amount = hour_based_amount
        applied_leave_deductions = Decimal(0)
        net = applied_hour_based_amount + attendance_bonus + leave_encashment - late_penalty - absence_deductions - retention_deduction

    net = max(net, Decimal(0))

    notes = []
    if late_penalty > 0:
        ld_str = f" on {', '.join(late_dates)}" if late_dates else ""
        notes.append(f"Late{ld_str}: -{round(late_penalty, 2)}")
    if absence_deductions > 0:
        ad_str = f" on {', '.join(absent_dates)}" if absent_dates else ""
        hd_str = f" (Half days: {', '.join(half_day_dates)})" if half_day_dates else ""
        notes.append(f"Absent{ad_str}{hd_str}: -{round(absence_deductions, 2)}")
    if applied_leave_deductions > 0:
        lv_str = f" ({', '.join(leave_dates)})" if leave_dates else ""
        notes.append(f"Leave{lv_str}: -{round(applied_leave_deductions, 2)}")
    if retention_deduction > 0:
        notes.append(f"Retention ({faculty_profile.salary_retention_percentage}%): -{round(retention_deduction, 2)}")
    deduction_note_str = ", ".join(notes)

    # 10. Create PaySlip
    payslip = PaySlip.objects.create(
        payroll_run=payroll_run,
        faculty=faculty_profile,
        basic_salary=basic_salary,
        total_session_hours=total_hours,
        hour_based_amount=applied_hour_based_amount,
        late_penalty=late_penalty,
        late_penalty_minutes=total_late_penalty_minutes,
        per_day_deduction_log=per_day_deduction_log,
        absence_deductions=absence_deductions,
        leave_deductions=applied_leave_deductions,
        retention_deduction=retention_deduction,
        attendance_bonus=attendance_bonus,
        leave_encashment=leave_encashment,
        deduction_note=deduction_note_str,
        net_salary=net,
        leaves_taken=int(leave_days),
        working_days=working_days,
        sessions_conducted=sessions_count,
    )

    # 11. Save Late penalty logs (per session)
    for detail in session_late_details:
        SessionLatePenaltyLog.objects.create(
            payslip=payslip,
            session_report=detail['session'],
            scheduled_time=detail['scheduled_time'],
            actual_start=detail['actual_start'],
            late_minutes=detail['late_minutes'],
            penalty_amount=Decimal(0), # Aggregated penalty is on the payslip level now
            grace_applied=detail['grace_applied'],
        )

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
    fac_hourly_rate = faculty_profile.hourly_rate if faculty_profile.hourly_rate > 0 else faculty_profile.user.hourly_rate
    fac_session_hours = faculty_profile.session_hours if faculty_profile.session_hours > 0 else faculty_profile.user.session_hours
    fac_salary = faculty_profile.salary if faculty_profile.salary > 0 else faculty_profile.user.salary
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
    daily_stats = defaultdict(lambda: {'total_hours': Decimal(0), 'gross_salary': Decimal(0), 'deduction': Decimal(0), 'late_minutes': 0, 'penalty_minutes': 0})

    for s in sessions:
        session_dates.add(s.session_date)
        hours = Decimal(s.duration_minutes) / Decimal(60)
        subject_hours[s.subject_id] += hours
        total_session_minutes += Decimal(s.duration_minutes)
        
        d_str = s.session_date.strftime('%Y-%m-%d')
        daily_stats[d_str]['total_hours'] += hours
        rate = get_subject_hourly_rate(faculty_profile, s.subject, month, year) if hasattr(s, 'subject') and s.subject else fac_hourly_rate
        daily_stats[d_str]['gross_salary'] += hours * rate

    qr_logs = FacultyQRScanLog.objects.filter(
        faculty=faculty_profile,
        scanned_at__year=year,
        scanned_at__month=month,
    ).order_by('scanned_at')

    # Group QR logs by LOCAL date (not UTC) to avoid date crossing at midnight IST
    from django.utils import timezone as dj_timezone
    qr_by_date = defaultdict(list)
    for log in qr_logs:
        local_scanned = dj_timezone.localtime(log.scanned_at)
        qr_by_date[local_scanned.date()].append(log)

    qr_extra_minutes = Decimal(0)
    qr_slot_deviation = defaultdict(lambda: {'late_in': Decimal(0), 'early_out': Decimal(0)})

    for log_date, logs in qr_by_date.items():
        if log_date in session_dates:
            continue
        check_ins = [l for l in logs if l.scan_type == 'check_in']
        check_outs = [l for l in logs if l.scan_type == 'check_out']
        if check_ins and check_outs:
            first_in_local = dj_timezone.localtime(min(l.scanned_at for l in check_ins))
            last_out_local = dj_timezone.localtime(max(l.scanned_at for l in check_outs))
            actual_in_time = first_in_local.time()
            actual_out_time = last_out_local.time()
            diff_minutes = Decimal((last_out_local - first_in_local).total_seconds()) / Decimal(60)

            from batches.models import TimetableSlot
            from django.db.models import Q
            dow = log_date.weekday()
            slots = TimetableSlot.objects.filter(
                Q(day_of_week=dow) | Q(session_date=log_date),
                faculty=faculty_profile,
            )
            scheduled_minutes = Decimal(0)
            for slot in slots:
                if slot.start_time and slot.end_time:
                    s_dt = datetime.combine(log_date, slot.start_time)
                    e_dt = datetime.combine(log_date, slot.end_time)
                    if e_dt < s_dt:
                        e_dt += timedelta(days=1)
                    scheduled_minutes += Decimal((e_dt - s_dt).total_seconds()) / Decimal(60)

                    actual_in_dt = datetime.combine(log_date, actual_in_time)
                    actual_out_dt = datetime.combine(log_date, actual_out_time)
                    late_in = max(Decimal(0), Decimal((actual_in_dt - s_dt).total_seconds()) / Decimal(60))
                    early_out = max(Decimal(0), Decimal((e_dt - actual_out_dt).total_seconds()) / Decimal(60))
                    d_str = log_date.strftime('%Y-%m-%d')
                    qr_slot_deviation[d_str]['late_in'] += late_in
                    qr_slot_deviation[d_str]['early_out'] += early_out

            if scheduled_minutes > 0:
                diff_minutes = min(diff_minutes, scheduled_minutes)

            qr_extra_minutes += max(diff_minutes, Decimal(0))

            if diff_minutes > 0:
                d_str = log_date.strftime('%Y-%m-%d')
                daily_stats[d_str]['total_hours'] += diff_minutes / Decimal(60)
                daily_stats[d_str]['gross_salary'] += (diff_minutes / Decimal(60)) * fac_hourly_rate

    # total_hours: only actual hours worked (no guaranteed base session_hours inflation)
    total_hours = (total_session_minutes + qr_extra_minutes) / Decimal(60)

    hour_based_amount = Decimal(0)
    for subject_id, hours in subject_hours.items():
        from batches.models import Subject
        try:
            subject = Subject.objects.get(id=subject_id)
        except Subject.DoesNotExist:
            subject = None
        rate = get_subject_hourly_rate(faculty_profile, subject, month, year) if subject else fac_hourly_rate
        hour_based_amount += hours * rate

    # Add QR-only hours at default rate (no base session_hours inflation for visiting/part-time)
    qr_extra_hours = qr_extra_minutes / Decimal(60)
    hour_based_amount += qr_extra_hours * fac_hourly_rate
    # NOTE: fac_session_hours is NOT added here.

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
    leave_dates = []
    for l in approved_leaves:
        leave_dates.append(f"{l.from_date.strftime('%Y-%m-%d')} to {l.to_date.strftime('%Y-%m-%d')}")
    if fac_hourly_rate != Decimal(0):
        daily_rate = Decimal(0)
    else:
        daily_rate = fac_salary / Decimal(30) if fac_salary else Decimal(0)
    leave_deductions = Decimal(leave_days) * daily_rate

    working_days = sum(1 for d in range(1, calendar.monthrange(year, month)[1] + 1)
                       if calendar.weekday(year, month, d) < 5)

    # 5. Compute deduction rates and late penalty
    if faculty_profile.employment_type == 'full_time':
        retention_pct = faculty_profile.salary_retention_percentage or Decimal(0)
        effective_salary = fac_salary * (1 - retention_pct / Decimal(100)) if fac_salary else Decimal(0)
        if faculty_profile.work_start_time and faculty_profile.work_end_time:
            s_dt = datetime.combine(datetime.today(), faculty_profile.work_start_time)
            e_dt = datetime.combine(datetime.today(), faculty_profile.work_end_time)
            if e_dt < s_dt:
                e_dt += timedelta(days=1)
            work_mins = Decimal((e_dt - s_dt).total_seconds()) / Decimal(60)
            if work_mins > 0:
                implicit_deduction_per_minute = (effective_salary / Decimal(30)) / work_mins
            else:
                implicit_deduction_per_minute = (effective_salary / Decimal(30)) / Decimal(8) / Decimal(60) if effective_salary else Decimal(0)
        else:
            implicit_deduction_per_minute = (effective_salary / Decimal(30)) / Decimal(8) / Decimal(60) if effective_salary else Decimal(0)
    else:
        implicit_deduction_per_minute = fac_hourly_rate / Decimal(60) if fac_hourly_rate else Decimal(0)

    deduction_rate = policy.deduction_per_minute if policy and policy.deduction_per_minute > 0 else implicit_deduction_per_minute
    grace = policy.grace_period_minutes if policy else 5
    max_deduction = policy.max_deduction_per_session if policy and policy.max_deduction_per_session > 0 else Decimal('999999')

    late_penalty = Decimal(0)
    late_half_days = 0
    days_late_15_mins = 0
    total_late_penalty_minutes = 0

    # Compute session-based late/early deviations
    daily_delays = defaultdict(int)

    for s in sessions:
        from batches.models import TimetableSlot
        scheduled_time = s.start_time
        scheduled_end_time = s.end_time
        dow = s.session_date.weekday()
        slot = TimetableSlot.objects.filter(batch_id=s.batch_id, subject_id=s.subject_id, day_of_week=dow).first()
        if slot and slot.start_time:
            scheduled_time = slot.start_time
        if slot and slot.end_time:
            scheduled_end_time = slot.end_time

        sched_dt = datetime.combine(s.session_date, scheduled_time)
        actual_dt = datetime.combine(s.session_date, s.start_time)
        diff = (actual_dt - sched_dt).total_seconds() / 60

        sched_end_dt = datetime.combine(s.session_date, scheduled_end_time)
        actual_end_dt = datetime.combine(s.session_date, s.end_time)
        if sched_end_dt < sched_dt:
            sched_end_dt += timedelta(days=1)
        if actual_end_dt < actual_dt:
            actual_end_dt += timedelta(days=1)
        diff_end = (sched_end_dt - actual_end_dt).total_seconds() / 60

        late_in_min = max(0, int(diff))
        early_out_min = max(0, int(diff_end))
        total_session_diff = late_in_min + early_out_min

        if total_session_diff > 0:
            daily_delays[s.session_date] += total_session_diff

    if faculty_profile.employment_type in ('visiting', 'part_time', 'contract'):
        # ── Visiting/Part-time: 5-minute COMBINED buffer per slot ──────────────────
        for d_date, d_delay in daily_delays.items():
            d_str = d_date.strftime('%Y-%m-%d')
            daily_stats[d_str]['late_minutes'] = d_delay
            if d_delay > grace:
                penalty_min = d_delay - grace
                day_penalty = min(Decimal(penalty_min) * deduction_rate, max_deduction)
                late_penalty += day_penalty
                total_late_penalty_minutes += penalty_min
                daily_stats[d_str]['penalty_minutes'] = penalty_min
                daily_stats[d_str]['deduction'] += day_penalty

        # QR-based deviation (dates without session reports)
        for d_str, deviation in qr_slot_deviation.items():
            total_dev = deviation['late_in'] + deviation['early_out']
            daily_stats[d_str]['late_minutes'] = int(total_dev)
            if total_dev > Decimal(grace):
                penalty_min = int(total_dev - Decimal(grace))
                day_penalty = min(Decimal(penalty_min) * deduction_rate, max_deduction)
                late_penalty += day_penalty
                total_late_penalty_minutes += penalty_min
                daily_stats[d_str]['penalty_minutes'] = penalty_min
                daily_stats[d_str]['deduction'] += day_penalty
    else:
        # ── Full-time: legacy approach ──────────────────────────────────────────────
        for log_date, logs in qr_by_date.items():
            for log in logs:
                daily_delays[log_date] += log.late_minutes
                daily_delays[log_date] += log.early_minutes

        for d_date, d_delay in daily_delays.items():
            if d_date.weekday() == 6:
                continue

            d_str = d_date.strftime('%Y-%m-%d')
            daily_stats[d_str]['late_minutes'] = d_delay

            if d_delay >= 60:
                late_half_days += 1
            else:
                if d_delay >= 15:
                    days_late_15_mins += 1

                if d_delay > grace:
                    penalty_min = d_delay - grace
                    day_penalty = min(Decimal(penalty_min) * deduction_rate, max_deduction)
                    late_penalty += day_penalty
                    total_late_penalty_minutes += penalty_min
                    daily_stats[d_str]['penalty_minutes'] = penalty_min
                    daily_stats[d_str]['deduction'] += day_penalty

    per_day_deduction_log = []
    for d_str, stat in sorted(daily_stats.items()):
        net_salary = max(Decimal(0), stat['gross_salary'] - stat['deduction'])
        per_day_deduction_log.append({
            'date': d_str,
            'total_hours': str(round(stat['total_hours'], 2)),
            'gross_salary': str(round(stat['gross_salary'], 2)),
            'deduction': str(round(stat['deduction'], 2)),
            'net_salary': str(round(net_salary, 2)),
            'late_minutes': stat['late_minutes'],
            'penalty_minutes': stat['penalty_minutes'],
            'penalty_amount': str(round(stat['deduction'], 2)),
        })

    late_half_days += (days_late_15_mins // 3)

    days_with_attendance = len(session_dates | set(qr_by_date.keys()))
    
    from datetime import date
    today = date.today()
    if year < today.year or (year == today.year and month < today.month):
        working_days_passed = working_days
    elif year == today.year and month == today.month:
        last_day = min(today.day, calendar.monthrange(year, month)[1])
        working_days_passed = sum(1 for d in range(1, last_day + 1) if calendar.weekday(year, month, d) < 5)
    else:
        working_days_passed = 0
        
    absent_days = Decimal(max(0, working_days_passed - days_with_attendance))
    absent_days += Decimal(late_half_days) * Decimal('0.5')

    absence_deduction_rate = policy.absence_deduction_per_day if policy and policy.absence_deduction_per_day > 0 else daily_rate
    absence_deductions = absent_days * absence_deduction_rate

    attendance_bonus = Decimal(0)
    if working_days > 0:
        attendance_percentage = (Decimal(days_with_attendance) / Decimal(working_days)) * 100
        if attendance_percentage > Decimal(80):
            attendance_bonus = daily_rate

    basic_salary = fac_salary if faculty_profile.employment_type == 'full_time' else Decimal(0)
    retention_deduction = Decimal(0)
    if faculty_profile.salary_retention_percentage > 0:
        gross_salary = basic_salary + hour_based_amount
        retention_deduction = gross_salary * (faculty_profile.salary_retention_percentage / Decimal(100))

    leave_encashment = Decimal(0)
    if month == 3:
        from leave.models import LeaveBalance
        balances = LeaveBalance.objects.filter(user=faculty_profile.user, year=year - 1)
        for bal in balances:
            if bal.remaining_days > Decimal(0):
                leave_encashment += bal.remaining_days * daily_rate

    if faculty_profile.employment_type == 'full_time':
        applied_hour_based_amount = hour_based_amount
        applied_leave_deductions = leave_deductions
        net = (basic_salary + applied_hour_based_amount + attendance_bonus + leave_encashment
               - late_penalty - absence_deductions
               - applied_leave_deductions - retention_deduction)
    else:
        applied_hour_based_amount = hour_based_amount
        applied_leave_deductions = Decimal(0)
        net = applied_hour_based_amount + attendance_bonus + leave_encashment - late_penalty - absence_deductions - retention_deduction

    net = max(net, Decimal(0))

    return {
        'basic_salary': str(basic_salary),
        'total_session_hours': str(round(total_hours, 2)),
        'hour_based_amount': str(round(applied_hour_based_amount, 2)),
        'late_penalty': str(round(late_penalty, 2)),
        'late_penalty_minutes': total_late_penalty_minutes,
        'per_day_deduction_log': per_day_deduction_log,
        'absence_deductions': str(round(absence_deductions, 2)),
        'leave_deductions': str(round(applied_leave_deductions, 2)),
        'retention_deduction': str(round(retention_deduction, 2)),
        'attendance_bonus': str(round(attendance_bonus, 2)),
        'leave_encashment': str(round(leave_encashment, 2)),
        'bonus': "0.00",
        'other_deductions': "0.00",
        'net_salary': str(round(net, 2)),
        'leaves_taken': int(leave_days),
        'working_days': working_days,
        'sessions_conducted': sessions_count,
    }


# Roles that are considered employees for payroll (not students/parents/super_admin)
EMPLOYEE_ROLES = [
    'branch_manager', 'admin_senior_executive', 'admin_executive',
    'front_desk', 'counsellor', 'sales_senior_executive', 'sales_executive',
    'tele_caller', 'exam_supervisor', 'paper_checker', 'accountant',
    'house_keeping', 'security',
]


def compute_payslip_for_user(user, month, year, payroll_run):
    """
    Simplified payroll computation for non-faculty employees.
    Uses User model fields (salary, hourly_rate, employment_type) directly.
    No session reports or chapter-based hour tracking — just:
      - base salary / hourly attendance
      - leave deductions (unpaid)
      - absence deductions
      - late penalty (from LateEntryRecord)
      - retention deduction
      - attendance bonus
    - house_keeping/security: NO leave option; instead 2 Sundays required/month:
      * attend only 1 Sunday → deduct 1 day's pay (sunday_deduction)
      * attend 3+ Sundays → add 1 extra paid day (sunday_bonus)
      * Sundays excluded from regular working_days/days_attended
    - paper_checker: **per paper checked ONLY** (MarkSheet where paper_checker=user, is_submitted=True, checked in payroll month).
      Uses user.per_paper_rate (added to User model; defaults to 50 if 0). 
      Grace: 5 days after exam.scheduled_date. Then incremental penalty: first 7 days late=5%, next 7=10%, next=15% etc (5% * bracket).
      Penalty folded into `late_penalty`; paper amount into `hour_based_amount`; sessions_conducted = papers_checked.
      No attendance/leave/sunday/absence calcs applied for this role. Backward compatible.
    """
    from .models import PaySlip, LateEntryPolicy
    from leave.models import LeaveApplication
    from attendance.models import EmployeeAttendanceRecord

    role = getattr(user, 'role', '')

    if role == 'paper_checker':
        # Per-paper payroll with late penalty + recheck handling + checker query support.
        # Removes count for pending/approved rechecks OR open queries.
        # For queries raised *after recheck starts*, payment (paper count) is cut/withheld
        # until query status='resolved' (then included in next payroll run).
        # Queries examples: answer_key_not_available, etc. (see QUERY_TYPE_CHOICES).
        from results.models import MarkSheet
        from django.db.models import Q
        papers_qs = MarkSheet.objects.filter(
            paper_checker=user,
            is_submitted=True,
            checked_at__year=year,
            checked_at__month=month,
        ).exclude(
            recheck_requests__status__in=['approval_pending', 'approved']
        ).exclude(
            queries__status='open'
        ).select_related('exam').distinct()
        papers_checked = papers_qs.count()
        per_paper_rate = getattr(user, 'per_paper_rate', Decimal('0'))
        if per_paper_rate <= 0:
            per_paper_rate = Decimal('50.00')  # fallback; update User profile as needed
        paper_amount = Decimal(papers_checked) * per_paper_rate
        late_submission_penalty = Decimal(0)
        for ms in papers_qs:
            if ms.exam and ms.exam.scheduled_date and ms.checked_at:
                due_date = ms.exam.scheduled_date + timedelta(days=5)
                checked_date = ms.checked_at.date()
                if checked_date > due_date:
                    days_late = (checked_date - due_date).days
                    bracket = (days_late // 7) + 1
                    penalty_pct = min(Decimal(5 * bracket), Decimal(100))
                    late_submission_penalty += per_paper_rate * (penalty_pct / Decimal(100))
        basic_salary = Decimal(0)
        total_hours = Decimal(papers_checked)
        hour_based_amount = paper_amount
        late_penalty = late_submission_penalty
        absence_deductions = Decimal(0)
        leave_deductions = Decimal(0)
        attendance_bonus = Decimal(0)
        retention_deduction = Decimal(0)
        leave_encashment = Decimal(0)
        working_days = 0
        sessions_conducted = papers_checked
        leaves_taken = 0
        if getattr(user, 'salary_retention_percentage', 0) > 0:
            retention_deduction = paper_amount * (Decimal(user.salary_retention_percentage) / Decimal(100))
        net = paper_amount - late_penalty - retention_deduction
        net = max(net, Decimal(0))
        # Delete existing for regeneration
        PaySlip.objects.filter(payroll_run=payroll_run, user=user, faculty__isnull=True).delete()
        payslip = PaySlip.objects.create(
            payroll_run=payroll_run,
            faculty=None,
            user=user,
            basic_salary=basic_salary,
            total_session_hours=total_hours,
            hour_based_amount=hour_based_amount,
            late_penalty=late_penalty,
            absence_deductions=absence_deductions,
            leave_deductions=leave_deductions,
            retention_deduction=retention_deduction,
            attendance_bonus=attendance_bonus,
            leave_encashment=leave_encashment,
            net_salary=net,
            leaves_taken=leaves_taken,
            working_days=working_days,
            sessions_conducted=sessions_conducted,
        )
        return payslip

    # 1. Working days in month (Mon-Fri for most; Sundays excluded from pay for HK/security)
    working_days = sum(1 for d in range(1, calendar.monthrange(year, month)[1] + 1)
                       if calendar.weekday(year, month, d) < 5)

    # 2. Daily rate
    if user.salary and user.salary > 0:
        daily_rate = user.salary / Decimal(30)
    elif user.hourly_rate and user.hourly_rate > 0:
        daily_rate = user.hourly_rate * Decimal(8)  # 8-hour workday
    else:
        daily_rate = Decimal(0)

    basic_salary = user.salary if user.employment_type == 'full_time' else Decimal(0)

    # 3. Attendance-based hours (from EmployeeAttendanceRecord)
    # Exclude Sunday for house_keeping/security per requirement
    qs = EmployeeAttendanceRecord.objects.filter(
        user=user,
        date__year=year,
        date__month=month,
        status__in=['present', 'late', 'half_day'],
    )
    if role in ['house_keeping', 'security']:
        qs = qs.exclude(date__week_day=1)  # Django week_day: 1=Sunday
    attendance_records = qs
    days_attended = attendance_records.count()

    # Special Sunday rules for housekeeping/security (2 Sundays required per month)
    # - If only 1 Sunday attended: deduct 1 day's pay (cut 1 "leave")
    # - If 3+ Sundays attended: add 1 extra paid day to payslip
    sunday_deduction = Decimal(0)
    sunday_bonus = Decimal(0)
    if role in ['house_keeping', 'security']:
        sunday_qs = EmployeeAttendanceRecord.objects.filter(
            user=user,
            date__year=year,
            date__month=month,
            date__week_day=1,  # Sunday
            status__in=['present', 'late', 'half_day'],
        )
        sunday_attended = sunday_qs.count()
        if sunday_attended < 2:
            missing = 2 - sunday_attended
            sunday_deduction = Decimal(missing) * daily_rate
        elif sunday_attended >= 3:
            sunday_bonus = daily_rate  # add one day

    # Also count FacultyQRScanLog if user has a faculty profile (backward compat)
    total_hours = Decimal(0)
    hour_based_amount = Decimal(0)

    if user.employment_type != 'full_time' and user.hourly_rate:
        # Calculate actual hours from attendance check-in/check-out
        for rec in attendance_records:
            if rec.checked_in_at and rec.checked_out_at:
                diff_hours = Decimal((rec.checked_out_at - rec.checked_in_at).total_seconds()) / Decimal(3600)
                total_hours += max(diff_hours, Decimal(0))
        hour_based_amount = total_hours * user.hourly_rate

    # 4. Leave deductions (unpaid only)
    approved_leaves = LeaveApplication.objects.filter(
        applied_by=user,
        status='approved',
        from_date__year=year,
        from_date__month=month,
        leave_type='unpaid',
    )
    leave_days = sum(l.total_days for l in approved_leaves)
    leave_dates = []
    for l in approved_leaves:
        leave_dates.append(f"{l.from_date.strftime('%Y-%m-%d')} to {l.to_date.strftime('%Y-%m-%d')}")
    leave_deductions = Decimal(leave_days) * daily_rate if user.employment_type == 'full_time' else Decimal(0)

    # 5. Late penalty 
    from leave.models import LateEntryRecord
    late_entries = LateEntryRecord.objects.filter(
        user=user,
        date__year=year,
        date__month=month,
    )

    policy = LateEntryPolicy.objects.filter(branch=user.branch, is_active=True).first() if user.branch else None
    grace = policy.grace_period_minutes if policy else 5

    late_penalty = Decimal(0)
    if user.employment_type == 'full_time':
        if user.work_start_time and user.work_end_time:
            s_dt = datetime.combine(datetime.today(), user.work_start_time)
            e_dt = datetime.combine(datetime.today(), user.work_end_time)
            if e_dt < s_dt:
                e_dt += timedelta(days=1)
            work_mins = Decimal((e_dt - s_dt).total_seconds()) / Decimal(60)
            if work_mins > 0:
                deduction_per_minute = (user.salary / Decimal(30)) / work_mins
            else:
                deduction_per_minute = (user.salary / Decimal(30)) / Decimal(8) / Decimal(60) if user.salary else Decimal(0)
        else:
            deduction_per_minute = (user.salary / Decimal(30)) / Decimal(8) / Decimal(60) if user.salary else Decimal(0)
    else:
        deduction_per_minute = user.hourly_rate / Decimal(60) if user.hourly_rate else Decimal(0)

    # Don't use policy.deduction_per_minute for these users if we want the actual salary deduction
    # but keep it if policy overrides
    # if policy and policy.deduction_per_minute > 0:
    #     deduction_per_minute = policy.deduction_per_minute

    max_deduction = policy.max_deduction_per_session if policy and policy.max_deduction_per_session > 0 else Decimal('999999')

    daily_delays = defaultdict(int)
    for entry in late_entries:
        daily_delays[entry.date] += entry.late_minutes
        
    for rec in attendance_records:
        if rec.checked_in_at and user.work_start_time:
            s_time = user.work_start_time
            from django.utils import timezone
            local_checkin = timezone.localtime(rec.checked_in_at)
            s_dt = datetime.combine(rec.date, s_time)
            if local_checkin.replace(tzinfo=None) > s_dt:
                diff = (local_checkin.replace(tzinfo=None) - s_dt).total_seconds() / 60
                daily_delays[rec.date] += int(diff)
                
        if rec.checked_out_at and user.work_end_time:
            e_time = user.work_end_time
            from django.utils import timezone
            local_checkout = timezone.localtime(rec.checked_out_at)
            e_dt = datetime.combine(rec.date, e_time)
            if user.work_start_time and user.work_end_time < user.work_start_time:
                e_dt += timedelta(days=1)
                
            if local_checkout.replace(tzinfo=None) < e_dt:
                diff = (e_dt - local_checkout.replace(tzinfo=None)).total_seconds() / 60
                daily_delays[rec.date] += int(diff)

    late_dates = []
    for d_date, d_delay in daily_delays.items():
        if d_date.weekday() == 6:
            continue
        if d_delay > grace:
            penalty_min = d_delay - grace
            late_penalty += min(Decimal(penalty_min) * deduction_per_minute, max_deduction)
            late_dates.append(d_date.strftime('%Y-%m-%d'))
            
    if role in ['house_keeping', 'security']:
        late_penalty = Decimal(0)
        late_dates = []

    from datetime import date
    today = date.today()
    if year < today.year or (year == today.year and month < today.month):
        working_days_passed = working_days
    elif year == today.year and month == today.month:
        last_day = min(today.day, calendar.monthrange(year, month)[1])
        working_days_passed = sum(1 for d in range(1, last_day + 1) if calendar.weekday(year, month, d) < 5)
    else:
        working_days_passed = 0
        last_day = 0

    attended_dates = set(attendance_records.values_list('date', flat=True))
    absent_dates = []
    for d in range(1, last_day + 1):
        if calendar.weekday(year, month, d) < 5:
            curr_date = date(year, month, d)
            if curr_date not in attended_dates:
                absent_dates.append(curr_date.strftime('%Y-%m-%d'))

    absent_days = Decimal(max(0, working_days_passed - days_attended))
    absence_deduction_rate = policy.absence_deduction_per_day if policy and policy.absence_deduction_per_day > 0 else daily_rate
    absence_deductions = absent_days * absence_deduction_rate
    absence_deductions += sunday_deduction  # include Sunday shortfall deduction for HK/security

    # 7. Attendance bonus
    attendance_bonus = Decimal(0)
    if working_days > 0:
        attendance_percentage = (Decimal(days_attended) / Decimal(working_days)) * 100
        if attendance_percentage > Decimal(80):
            attendance_bonus = daily_rate
    attendance_bonus += sunday_bonus  # extra day bonus if 3+ Sundays attended

    # 8. Retention deduction
    retention_deduction = Decimal(0)
    if user.salary_retention_percentage and user.salary_retention_percentage > 0:
        gross_salary = basic_salary + hour_based_amount
        retention_deduction = gross_salary * (user.salary_retention_percentage / Decimal(100))

    # 9. Leave encashment (March)
    leave_encashment = Decimal(0)
    if month == 3:
        from leave.models import LeaveBalance
        balances = LeaveBalance.objects.filter(user=user, year=year - 1)
        for bal in balances:
            if bal.remaining_days > Decimal(0):
                leave_encashment += bal.remaining_days * daily_rate
                bal.used_days += bal.remaining_days
                bal.save(update_fields=['used_days'])

    # 10. Net salary
    if user.employment_type == 'full_time':
        net = (basic_salary + hour_based_amount + attendance_bonus + leave_encashment
               - late_penalty - absence_deductions - leave_deductions - retention_deduction)
    else:
        net = (hour_based_amount + attendance_bonus + leave_encashment
               - late_penalty - absence_deductions - retention_deduction)

    net = max(net, Decimal(0))

    # 11. Create PaySlip
    # Delete existing payslip for this user in this payroll run (for regeneration)
    PaySlip.objects.filter(payroll_run=payroll_run, user=user, faculty__isnull=True).delete()

    notes = []
    if late_penalty > 0:
        ld_str = f" on {', '.join(late_dates)}" if late_dates else ""
        notes.append(f"Late{ld_str}: -{round(late_penalty, 2)}")
    if absence_deductions > 0:
        ad_str = f" on {', '.join(absent_dates)}" if absent_dates else ""
        notes.append(f"Absent{ad_str}: -{round(absence_deductions, 2)}")
    if leave_deductions > 0:
        lv_str = f" ({', '.join(leave_dates)})" if leave_dates else ""
        notes.append(f"Leave{lv_str}: -{round(leave_deductions, 2)}")
    if retention_deduction > 0:
        notes.append(f"Retention ({user.salary_retention_percentage}%): -{round(retention_deduction, 2)}")
    if sunday_deduction > 0:
        notes.append(f"Sunday Shortfall: -{round(sunday_deduction, 2)}")
    deduction_note_str = ", ".join(notes)

    payslip = PaySlip.objects.create(
        payroll_run=payroll_run,
        faculty=None,
        user=user,
        basic_salary=basic_salary,
        total_session_hours=total_hours,
        hour_based_amount=hour_based_amount,
        late_penalty=late_penalty,
        absence_deductions=absence_deductions,
        leave_deductions=leave_deductions,
        retention_deduction=retention_deduction,
        attendance_bonus=attendance_bonus,
        leave_encashment=leave_encashment,
        deduction_note=deduction_note_str,
        net_salary=net,
        leaves_taken=int(leave_days),
        working_days=working_days,
        sessions_conducted=0,
    )

    return payslip
