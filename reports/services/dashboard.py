"""Dashboard KPI aggregations."""
from datetime import timedelta
from django.utils import timezone
from django.db.models import Count, Sum, Q, F, Case, When, Value, FloatField
from django.db.models.functions import Cast

from students.models import Student
from onboarding.models import Admission
from attendance.models import AttendanceRecord
from fees.models import StudentFee, Payment
from exams.models import Exam
from results.models import MarkSheet
from leads.models import Lead
from branch.models import Branch
from batches.models import Batch


def _branch_filter(user):
    """Return Q filter for branch scoping based on user role."""
    q = Q()
    org = getattr(user, 'organization', None)
    if org:
        q &= Q(branch__organization=org)
    role = getattr(user, 'role', None)
    if role == 'super_admin':
        return q
    bid = getattr(user, 'branch_id', None)
    if not bid and hasattr(user, 'profile'):
        bid = getattr(user.profile, 'branch_id', None)
    if bid:
        q &= Q(branch_id=bid)
    return q


def get_dashboard_data(user):
    now = timezone.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    today = now.date()
    bq = _branch_filter(user)

    # Students
    student_qs = Student.objects.filter(bq)
    total_active = student_qs.filter(status='active').count()

    # New admissions this month
    new_admissions = Admission.objects.filter(
        bq, status='enrolled', submitted_at__gte=month_start
    ).count()

    # Dropout rate
    total_ever = student_qs.count() or 1
    inactive = student_qs.filter(status='inactive').count()
    dropout_rate = round((inactive / total_ever) * 100, 2)

    # Attendance (current month)
    att_qs = AttendanceRecord.objects.filter(bq, date__gte=month_start.date(), date__lte=today)
    att_agg = att_qs.aggregate(
        total=Count('id'),
        present=Count('id', filter=Q(status__in=['present', 'late'])),
    )
    att_total = att_agg['total'] or 1
    att_rate = round((att_agg['present'] or 0) / att_total * 100, 2)

    # Attendance by branch
    att_by_branch = list(
        att_qs.values('branch_id', 'branch__name')
        .annotate(
            total=Count('id'),
            present=Count('id', filter=Q(status__in=['present', 'late'])),
        )
        .order_by('branch__name')
    )
    attendance_by_branch = [
        {
            'branch_id': r['branch_id'],
            'branch_name': r['branch__name'] or '',
            'attendance_rate': round((r['present'] / (r['total'] or 1)) * 100, 2),
        }
        for r in att_by_branch
    ]

    # Attendance by batch
    att_by_batch = list(
        att_qs.values('batch_id', 'batch__name')
        .annotate(
            total=Count('id'),
            present=Count('id', filter=Q(status__in=['present', 'late'])),
        )
        .order_by('batch__name')
    )
    attendance_by_batch = [
        {
            'batch_id': r['batch_id'],
            'batch_name': r['batch__name'] or '',
            'attendance_rate': round((r['present'] / (r['total'] or 1)) * 100, 2),
        }
        for r in att_by_batch
    ]

    # Fees
    # Build branch filter for StudentFee (uses student__branch_id)
    role = getattr(user, 'role', None)
    fee_bq = Q()
    org = getattr(user, 'organization', None)
    if org:
        fee_bq &= Q(student__branch__organization=org)
    if role == 'super_admin':
        pass
    else:
        bid = getattr(user, 'branch_id', None)
        if bid:
            fee_bq &= Q(student__branch_id=bid)

    fee_agg = StudentFee.objects.filter(fee_bq).aggregate(
        collected=Sum('amount_paid'),
        total_due=Sum(F('total_amount') - F('discount') - F('amount_paid')),
        overdue=Sum(
            Case(
                When(status='overdue', then=F('total_amount') - F('discount') - F('amount_paid')),
                default=Value(0),
                output_field=FloatField(),
            )
        ),
    )
    fee_collected = fee_agg['collected'] or 0
    fee_due = fee_agg['total_due'] or 0
    overdue_fees = fee_agg['overdue'] or 0

    # Upcoming exams
    upcoming = list(
        Exam.objects.filter(
            bq, is_deleted=False, scheduled_date__gte=today,
            status__in=['scheduled', 'draft']
        )
        .select_related('batch', 'subject')
        .order_by('scheduled_date')[:10]
        .values('id', 'title', 'scheduled_date', 'batch__name', 'subject__name')
    )
    upcoming_exams = [
        {
            'id': e['id'], 'title': e['title'],
            'scheduled_date': e['scheduled_date'],
            'batch_name': e['batch__name'],
            'subject_name': e['subject__name'],
        }
        for e in upcoming
    ]

    # Pending results
    pending_results = MarkSheet.objects.filter(
        exam__branch__in=Branch.objects.filter(bq if bq else Q()),
        is_submitted=False,
    ).count() if bq else MarkSheet.objects.filter(is_submitted=False).count()

    # CRM
    lead_qs = Lead.objects.filter(bq)
    open_leads = lead_qs.exclude(current_stage__in=['converted', 'lost']).count()
    pipeline = list(
        lead_qs.values('current_stage')
        .annotate(count=Count('id'))
        .order_by('current_stage')
    )
    crm_pipeline = [{'stage': p['current_stage'], 'count': p['count']} for p in pipeline]

    return {
        'total_active_students': total_active,
        'new_admissions_this_month': new_admissions,
        'dropout_rate': dropout_rate,
        'attendance_rate': att_rate,
        'attendance_by_branch': attendance_by_branch,
        'attendance_by_batch': attendance_by_batch,
        'fee_collected': fee_collected,
        'fee_due': fee_due,
        'overdue_fees': overdue_fees,
        'upcoming_exams': upcoming_exams,
        'pending_results': pending_results,
        'open_crm_leads': open_leads,
        'crm_pipeline': crm_pipeline,
    }
