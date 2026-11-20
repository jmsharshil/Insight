"""CRM / Lead conversion report service."""
from django.utils import timezone
from django.db.models import Count, Avg, Q, F
from django.db.models.functions import TruncDate
from leads.models import Lead, LeadStage
from core.utils import (
    get_lead_filter_q,
    RESTRICTED_ROLES,
    FULL_LEAD_ACCESS_ROLES,
    get_user_role,
    get_user_branch_id,
)


def get_lead_report(user, params=None):
    """Unified lead report using centralized get_lead_filter_q for scoping parity
    with dashboard and LeadListView (incl. front_desk as full-access role,
    restricted roles see only assigned_to=self, super_admin sees org + unassigned).
    """
    if params is None:
        params = {}

    q = get_lead_filter_q(user)

    branch_id = params.get('branch_id')
    from_date = params.get('from_date')
    to_date = params.get('to_date')
    assigned_to = params.get('assigned_to')

    if branch_id:
        q &= Q(branch_id=branch_id)
    if from_date:
        q &= Q(created_at__date__gte=from_date)
    if to_date:
        q &= Q(created_at__date__lte=to_date)
    if assigned_to:
        q &= Q(assigned_to_id=assigned_to)

    qs = Lead.objects.filter(q).select_related('assigned_to', 'branch')
    total = qs.count()

    # Stage counts
    stage_counts = dict(
        qs.values_list('current_stage')
        .annotate(c=Count('id'))
        .values_list('current_stage', 'c')
    )
    new = stage_counts.get('new', 0)
    contacted = stage_counts.get('contacted', 0)
    interested = stage_counts.get('interested', 0)
    visit = stage_counts.get('visit', 0)
    visited = stage_counts.get('visited', 0)
    follow_up = stage_counts.get('follow_up', 0)
    converted = stage_counts.get('converted', 0)
    lost = stage_counts.get('lost', 0)

    conversion_rate = round((converted / (total or 1)) * 100, 2)

    # Avg conversion days
    converted_leads = qs.filter(current_stage='converted')
    if converted_leads.exists():
        # Use stage history to find conversion time
        from django.db.models import Min, Max
        conv_times = []
        stage_data = (
            LeadStage.objects.filter(lead__in=converted_leads, stage='converted')
            .values('lead_id', 'changed_at')
        )
        lead_created = dict(
            converted_leads.values_list('id', 'created_at')
        )
        for sd in stage_data:
            created = lead_created.get(sd['lead_id'])
            if created and sd['changed_at']:
                delta = (sd['changed_at'] - created).days
                conv_times.append(delta)
        avg_conv_days = round(sum(conv_times) / len(conv_times), 1) if conv_times else 0
    else:
        avg_conv_days = 0

    # By source (reference field)
    by_source = list(
        qs.values('reference')
        .annotate(count=Count('id'))
        .order_by('-count')
    )
    by_source = [{'source': s['reference'] or 'unknown', 'count': s['count']} for s in by_source]

    # By counsellor — uses Admission.assigned_counsellor with same scoping
    # as get_lead_filter_q (RoleChecker + additional_roles support).
    # FULL_LEAD_ACCESS_ROLES see org + unassigned; restricted see only own.
    from onboarding.models import Admission
    role_checker = get_user_role(user)
    is_full_access = bool(role_checker and role_checker in FULL_LEAD_ACCESS_ROLES)
    is_restricted = bool(role_checker and role_checker in RESTRICTED_ROLES)

    adm_q = Q(assigned_counsellor__isnull=False)
    org = getattr(user, 'organization', None)
    if org:
        if is_full_access:
            adm_q &= Q(branch__organization=org) | Q(branch__isnull=True)
        else:
            adm_q &= Q(branch__organization=org)

    if is_restricted:
        adm_q &= Q(assigned_counsellor=user)
    elif not is_full_access:
        bid = get_user_branch_id(user)
        if bid:
            adm_q &= Q(branch_id=bid)

    if branch_id:
        adm_q &= Q(branch_id=branch_id)

    counsellor_data = list(
        Admission.objects.filter(adm_q)
        .values('assigned_counsellor_id', 'assigned_counsellor__name')
        .annotate(
            total_leads=Count('id'),
            converted=Count('id', filter=Q(status='enrolled')),
        )
        .order_by('-converted')
    )
    by_counsellor = [
        {
            'counsellor_id': c['assigned_counsellor_id'],
            'counsellor_name': c['assigned_counsellor__name'] or '',
            'total_leads': c['total_leads'],
            'converted': c['converted'],
            'conversion_rate': round((c['converted'] / (c['total_leads'] or 1)) * 100, 2),
        }
        for c in counsellor_data
    ]

    # Daily trend (last 30 days)
    now = timezone.now()
    thirty_ago = (now - timezone.timedelta(days=30)).date()
    trend_qs = qs.filter(created_at__date__gte=thirty_ago)
    daily = list(
        trend_qs.annotate(date=TruncDate('created_at'))
        .values('date')
        .annotate(count=Count('id'))
        .order_by('date')
    )
    daily_trend = [{'date': d['date'], 'count': d['count']} for d in daily]

    return {
        'total_leads': total,
        'new': new,
        'contacted': contacted,
        'interested': interested,
        'visit': visit,
        'visited': visited,
        'follow_up': follow_up,
        'converted': converted,
        'lost': lost,
        'conversion_rate': conversion_rate,
        'avg_conversion_days': avg_conv_days,
        'by_source': by_source,
        'by_counsellor': by_counsellor,
        'daily_trend': daily_trend,
    }
