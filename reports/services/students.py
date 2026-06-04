"""Student report service."""
from django.utils import timezone
from django.db.models import Count, Q
from django.db.models.functions import TruncMonth
from students.models import Student
from onboarding.models import Admission


def get_student_report(user, params):
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

    qs = Student.objects.filter(bq)

    course_id = params.get('course_id')
    batch_id = params.get('batch_id')
    if course_id:
        qs = qs.filter(course=course_id)
    if batch_id:
        qs = qs.filter(batch_id=batch_id)

    total = qs.count()
    active = qs.filter(status='active').count()
    inactive = total - active

    # New admissions filter
    now = timezone.now()
    month = int(params.get('month', now.month))
    year = int(params.get('year', now.year))
    adm_bq = Q()
    if org:
        adm_bq &= Q(branch__organization=org)
    if role != 'super_admin':
        bid = getattr(user, 'branch_id', None)
        if bid:
            adm_bq = Q(branch_id=bid)
    if branch_id:
        adm_bq &= Q(branch_id=branch_id)
    new_admissions = Admission.objects.filter(
        adm_bq, status='enrolled',
        submitted_at__year=year, submitted_at__month=month,
    ).count()

    # By course
    by_course = list(
        qs.values('course')
        .annotate(count=Count('id'))
        .order_by('course')
    )

    # By batch
    by_batch = list(
        qs.filter(batch__isnull=False)
        .values('batch_id', 'batch__name')
        .annotate(count=Count('id'))
        .order_by('batch__name')
    )
    by_batch = [
        {'batch_id': b['batch_id'], 'batch_name': b['batch__name'] or '', 'count': b['count']}
        for b in by_batch
    ]

    # Enrollment trend (last 12 months)
    twelve_months_ago = now - timezone.timedelta(days=365)
    trend = list(
        Student.objects.filter(bq, enrolled_at__gte=twelve_months_ago)
        .annotate(month=TruncMonth('enrolled_at'))
        .values('month')
        .annotate(count=Count('id'))
        .order_by('month')
    )
    enrollment_trend = [
        {'month': t['month'].strftime('%Y-%m'), 'count': t['count']}
        for t in trend
    ]

    return {
        'total_students': total,
        'active_students': active,
        'inactive_students': inactive,
        'new_admissions': new_admissions,
        'by_course': by_course,
        'by_batch': by_batch,
        'enrollment_trend': enrollment_trend,
    }
