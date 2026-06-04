"""Attendance report service."""
import calendar
from django.utils import timezone
from django.db.models import Count, Q, F
from django.db.models.functions import TruncDate, TruncWeek, TruncMonth, Concat
from django.db.models import Value, CharField
from attendance.models import AttendanceRecord, ViolationRecord


def get_attendance_report(user, params):
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
    batch_id = params.get('batch_id')
    if branch_id:
        bq &= Q(branch_id=branch_id)

    now = timezone.now()
    month = int(params.get('month', now.month))
    year = int(params.get('year', now.year))

    _, last_day = calendar.monthrange(year, month)
    from datetime import date
    start = date(year, month, 1)
    end = date(year, month, last_day)

    qs = AttendanceRecord.objects.filter(bq, date__gte=start, date__lte=end)
    if batch_id:
        qs = qs.filter(batch_id=batch_id)

    # Overall
    agg = qs.aggregate(
        total=Count('id'),
        present=Count('id', filter=Q(status__in=['present', 'late'])),
    )
    total = agg['total'] or 1
    att_pct = round((agg['present'] or 0) / total * 100, 2)

    # Students below 75%
    student_stats = list(
        qs.values('student_id', 'student__first_name', 'student__surname', 'student__admission_number')
        .annotate(
            total_days=Count('id'),
            present_days=Count('id', filter=Q(status__in=['present', 'late'])),
        )
        .order_by('student__first_name')
    )
    students = []
    below_75 = 0
    absentee_list = []
    for s in student_stats:
        pct = round((s['present_days'] / (s['total_days'] or 1)) * 100, 2)
        row = {
            'student_id': s['student_id'],
            'student_name': f"{s['student__first_name']} {s['student__surname']}".strip(),
            'admission_number': s['student__admission_number'] or '',
            'total_days': s['total_days'],
            'present_days': s['present_days'],
            'attendance_pct': pct,
        }
        students.append(row)
        if pct < 75:
            below_75 += 1
            absentee_list.append(row)

    # Daily trend
    daily = list(
        qs.values('date')
        .annotate(
            present=Count('id', filter=Q(status__in=['present', 'late'])),
            absent=Count('id', filter=Q(status='absent')),
            total=Count('id'),
        )
        .order_by('date')
    )
    daily_trend = [
        {
            'date': d['date'],
            'present': d['present'], 'absent': d['absent'], 'total': d['total'],
            'rate': round((d['present'] / (d['total'] or 1)) * 100, 2),
        }
        for d in daily
    ]

    # Weekly trend
    weekly = list(
        qs.annotate(week=TruncWeek('date'))
        .values('week')
        .annotate(
            total=Count('id'),
            present=Count('id', filter=Q(status__in=['present', 'late'])),
        )
        .order_by('week')
    )
    weekly_trend = [
        {'week': i + 1, 'rate': round((w['present'] / (w['total'] or 1)) * 100, 2)}
        for i, w in enumerate(weekly)
    ]

    # Monthly trend (last 6 months)
    six_ago = (now - timezone.timedelta(days=180)).date()
    monthly = list(
        AttendanceRecord.objects.filter(bq, date__gte=six_ago)
        .annotate(month=TruncMonth('date'))
        .values('month')
        .annotate(
            total=Count('id'),
            present=Count('id', filter=Q(status__in=['present', 'late'])),
        )
        .order_by('month')
    )
    monthly_trend = [
        {'month': m['month'].strftime('%Y-%m'), 'rate': round((m['present'] / (m['total'] or 1)) * 100, 2)}
        for m in monthly
    ]

    # Violation summary
    v_bq = Q()
    if org:
        v_bq &= Q(student__branch__organization=org)
    if role != 'super_admin':
        bid = getattr(user, 'branch_id', None)
        if bid:
            v_bq = Q(student__branch_id=bid)
    if branch_id:
        v_bq &= Q(student__branch_id=branch_id)
    violations = list(
        ViolationRecord.objects.filter(v_bq, date__gte=start, date__lte=end)
        .values('violation_type')
        .annotate(count=Count('id'))
        .order_by('violation_type')
    )
    violation_summary = [{'type': v['violation_type'], 'count': v['count']} for v in violations]

    return {
        'attendance_percentage': att_pct,
        'students_below_75': below_75,
        'daily_trend': daily_trend,
        'weekly_trend': weekly_trend,
        'monthly_trend': monthly_trend,
        'absentee_list': absentee_list,
        'violation_summary': violation_summary,
        'students': students,
    }
