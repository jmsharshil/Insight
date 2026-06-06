"""Leave report service."""
from django.utils import timezone
from django.db.models import Count, Sum, Q, F
from leave.models import LeaveBalance, LeaveApplication


def get_leave_report(user, params):
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

    now = timezone.now()
    year = int(params.get('year', now.year))

    bal_q = Q(year=year)
    if org:
        bal_q &= Q(user__organization=org)
    if role != 'super_admin':
        bid = getattr(user, 'branch_id', None)
        if bid:
            bal_q &= Q(user__branch_id=bid)
    if branch_id:
        bal_q &= Q(user__branch_id=branch_id)

    balances = list(
        LeaveBalance.objects.filter(bal_q)
        .values('user_id', 'user__name', 'leave_type', 'total_days', 'used_days', 'carried_forward')
        .order_by('user__name', 'leave_type')
    )
    leave_balance = [
        {
            'user_id': b['user_id'],
            'user_name': b['user__name'] or '',
            'leave_type': b['leave_type'],
            'total_days': b['total_days'],
            'used_days': b['used_days'],
            'remaining': float(b['total_days'] or 0) + float(b['carried_forward'] or 0) - float(b['used_days'] or 0),
        }
        for b in balances
    ]

    # Leave taken by type
    app_q = bq & Q(status='approved', from_date__year=year)
    taken_by_type = list(
        LeaveApplication.objects.filter(app_q)
        .values('leave_type')
        .annotate(total_days=Sum('total_days'), count=Count('id'))
        .order_by('leave_type')
    )
    leave_taken_by_type = [
        {
            'leave_type': t['leave_type'],
            'total_days': t['total_days'] or 0,
            'count': t['count'],
        }
        for t in taken_by_type
    ]

    # Pending approvals
    pending_q = bq & Q(status='approval_pending')
    pending_approvals = LeaveApplication.objects.filter(pending_q).count()

    return {
        'leave_balance': leave_balance,
        'leave_taken_by_type': leave_taken_by_type,
        'pending_approvals': pending_approvals,
    }
