"""Fee collection report service."""
from django.utils import timezone
from django.db.models import Sum, Count, Q, F, Value, FloatField, Case, When
from django.db.models.functions import TruncMonth
from fees.models import StudentFee, Payment


def get_fee_report(user, params):
    role = getattr(user, 'role', None)
    bq = Q()
    if role != 'super_admin':
        bid = getattr(user, 'branch_id', None)
        if bid:
            bq = Q(student__branch_id=bid)

    branch_id = params.get('branch_id')
    if branch_id:
        bq &= Q(student__branch_id=branch_id)

    now = timezone.now()
    month = int(params.get('month', now.month))
    year = int(params.get('year', now.year))
    course_id = params.get('course_id')

    sf_qs = StudentFee.objects.filter(bq)
    if course_id:
        sf_qs = sf_qs.filter(fee_structure__course_id=course_id)

    agg = sf_qs.aggregate(
        collected=Sum('amount_paid'),
        total_due=Sum(F('total_amount') - F('discount') - F('amount_paid')),
        pending=Sum(
            Case(When(status='pending', then=F('total_amount') - F('discount') - F('amount_paid')),
                 default=Value(0), output_field=FloatField())
        ),
        overdue=Sum(
            Case(When(status='overdue', then=F('total_amount') - F('discount') - F('amount_paid')),
                 default=Value(0), output_field=FloatField())
        ),
    )

    # Payment mode breakdown for the selected month/year
    pay_bq = Q()
    if role != 'super_admin':
        bid = getattr(user, 'branch_id', None)
        if bid:
            pay_bq = Q(student__branch_id=bid)
    if branch_id:
        pay_bq &= Q(student__branch_id=branch_id)

    pay_qs = Payment.objects.filter(
        pay_bq, status='verified',
        payment_date__year=year, payment_date__month=month,
    )
    mode_breakdown = list(
        pay_qs.values('payment_mode')
        .annotate(amount=Sum('amount'), count=Count('id'))
        .order_by('payment_mode')
    )
    payment_mode_breakdown = [
        {'mode': m['payment_mode'], 'amount': m['amount'] or 0, 'count': m['count']}
        for m in mode_breakdown
    ]

    # Student-wise breakdown (top 100 by due amount)
    student_rows = list(
        sf_qs.values('student_id', 'student__name', 'status')
        .annotate(
            sum_total=Sum('total_amount'),
            sum_paid=Sum('amount_paid'),
            amount_due=Sum(F('total_amount') - F('discount') - F('amount_paid')),
        )
        .order_by('-amount_due')[:100]
    )
    student_wise = [
        {
            'student_id': r['student_id'],
            'student_name': r['student__name'] or '',
            'total_amount': r['sum_total'] or 0,
            'amount_paid': r['sum_paid'] or 0,
            'amount_due': r['amount_due'] or 0,
            'status': r['status'] or 'pending',
        }
        for r in student_rows
    ]

    # Monthly trend (last 12 months)
    twelve_ago = now - timezone.timedelta(days=365)
    trend = list(
        Payment.objects.filter(pay_bq, status='verified', payment_date__gte=twelve_ago.date())
        .annotate(month=TruncMonth('payment_date'))
        .values('month')
        .annotate(collected=Sum('amount'))
        .order_by('month')
    )
    monthly_trend = [
        {'month': t['month'].strftime('%Y-%m'), 'collected': t['collected'] or 0}
        for t in trend
    ]

    return {
        'total_collected': agg['collected'] or 0,
        'total_due': agg['total_due'] or 0,
        'total_pending': agg['pending'] or 0,
        'total_overdue': agg['overdue'] or 0,
        'payment_mode_breakdown': payment_mode_breakdown,
        'student_wise_breakdown': student_wise,
        'monthly_trend': monthly_trend,
    }
