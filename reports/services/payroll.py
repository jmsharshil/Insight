"""Payroll report service."""
from django.db.models import Sum, Count, Avg, Q
from payroll.models import PayrollRun, PaySlip, SessionLatePenaltyLog
from faculty.models import SessionReport


def get_payroll_report(user, params):
    role = getattr(user, 'role', None)
    bq = Q()
    org = getattr(user, 'organization', None)
    if org:
        bq &= Q(branch__organization=org)
    if role != 'super_admin':
        bid = getattr(user, 'branch_id', None)
        if bid:
            bq = Q(branch_id=bid)

    branch_id = params.get('branch_id')
    if branch_id:
        bq &= Q(branch_id=branch_id)

    from django.utils import timezone
    now = timezone.now()
    month = int(params.get('month', now.month))
    year = int(params.get('year', now.year))

    runs = PayrollRun.objects.filter(bq, month=month, year=year)
    run_ids = list(runs.values_list('id', flat=True))

    slips = PaySlip.objects.filter(payroll_run_id__in=run_ids).select_related(
        'faculty__user'
    )

    agg = slips.aggregate(
        total_disbursed=Sum('net_salary'),
        faculty_count=Count('id'),
        avg_salary=Avg('net_salary'),
    )

    # Payroll summary
    payroll_summary = [
        {
            'faculty_id': str(ps.faculty.id),
            'faculty_name': ps.faculty.user.name if ps.faculty else '',
            'employee_id': ps.faculty.employee_id if ps.faculty else '',
            'basic_salary': ps.basic_salary,
            'hour_based_amount': ps.hour_based_amount,
            'late_penalty': ps.late_penalty,
            'absence_deductions': ps.absence_deductions,
            'leave_deductions': ps.leave_deductions,
            'bonus': ps.bonus,
            'net_salary': ps.net_salary,
            'is_disbursed': ps.is_disbursed,
        }
        for ps in slips
    ]

    # Hours taught
    hours_taught = [
        {
            'faculty_id': str(ps.faculty.id),
            'faculty_name': ps.faculty.user.name if ps.faculty else '',
            'total_hours': float(ps.total_session_hours),
            'sessions_conducted': ps.sessions_conducted,
        }
        for ps in slips
    ]

    # Penalties
    penalties = list(
        SessionLatePenaltyLog.objects.filter(payslip__payroll_run_id__in=run_ids)
        .select_related('payslip__faculty__user', 'session_report')
        .values(
            'payslip__faculty__user__name',
            'late_minutes', 'penalty_amount',
            'session_report__session_date',
        )[:100]
    )
    penalty_rows = [
        {
            'faculty_name': p['payslip__faculty__user__name'] or '',
            'late_minutes': p['late_minutes'],
            'penalty_amount': p['penalty_amount'],
            'session_date': p['session_report__session_date'],
        }
        for p in penalties
    ]

    # Disbursement status
    disb = list(
        slips.values('is_disbursed')
        .annotate(count=Count('id'), total_amount=Sum('net_salary'))
    )
    disbursement_status = [
        {
            'status': 'Disbursed' if d['is_disbursed'] else 'Pending',
            'count': d['count'],
            'total_amount': d['total_amount'] or 0,
        }
        for d in disb
    ]

    return {
        'total_disbursed': agg['total_disbursed'] or 0,
        'faculty_count': agg['faculty_count'] or 0,
        'average_salary': round(agg['avg_salary'] or 0, 2),
        'hours_taught': hours_taught,
        'payroll_summary': payroll_summary,
        'penalties': penalty_rows,
        'disbursement_status': disbursement_status,
    }
