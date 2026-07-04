"""Dashboard services for role-specific, highly optimized KPIs and data.
Uses heavy caching, query optimization (select_related, prefetch_related, aggregates),
and role-based data scoping for minimal response times.
"""
from datetime import timedelta
from django.utils import timezone
from django.db.models import Count, Sum, Q, F, Avg, Case, When, Value, FloatField
from django.core.cache import cache

from auth_user.models import User, NotificationHistory
from students.models import Student, ParentLink
from attendance.models import AttendanceRecord
from fees.models import StudentFee, Payment
from exams.models import Exam
from results.models import MarkSheet, PublishedResult
from leads.models import Lead
from batches.models import Batch, TimetableSlot
from faculty.models import FacultyProfile, SessionReport, FacultyQRScanLog
from payroll.models import PaySlip


def _get_cache_key(user):
    """Generate cache key specific to user/role/branch for cache isolation."""
    branch_id = str(user.branch_id or 'global')
    org_id = str(getattr(user.organization, 'id', 'global'))
    return f"dashboard:{user.role}:{user.id}:{branch_id}:{org_id}"


def _branch_filter(user, model=None):
    """Optimized branch/organization filter based on role."""
    q = Q()
    role = getattr(user, 'role', None)
    if hasattr(user, 'organization') and user.organization:
        q &= Q(organization=user.organization) if hasattr(model, 'organization') else Q(branch__organization=user.organization)
    if role == 'super_admin':
        return q
    bid = getattr(user, 'branch_id', None)
    if bid:
        if model and hasattr(model, 'branch'):
            q &= Q(branch_id=bid)
        elif 'branch' in str(model):
            q &= Q(branch_id=bid)
    return q


def get_role_dashboard(user):
    """Main entry point - cached per user/role."""
    cache_key = _get_cache_key(user)
    data = cache.get(cache_key)
    if data is not None:
        return data

    role = user.role
    now = timezone.now()
    today = now.date()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    thirty_days_ago = now - timedelta(days=30)

    # Common data with optimized queries
    common_data = {
        'current_date': today.isoformat(),
        'unread_notifications': NotificationHistory.objects.filter(
            user=user, is_read=False
        ).count(),
        'recent_notifications': list(
            NotificationHistory.objects.filter(user=user)
            .order_by('-created_at')[:5]
            .values('id', 'title', 'body', 'is_read', 'created_at')
        ),
    }

    if role in ('super_admin', 'branch_manager', 'admin_senior_executive', 'admin_executive', 'accountant'):
        data = _get_management_dashboard(user, now, today, month_start, thirty_days_ago)
    elif role in ('faculty', 'exam_supervisor', 'paper_checker'):
        data = _get_faculty_dashboard(user, now, today, month_start)
    elif role in ('student', 'parents'):
        data = _get_student_dashboard(user, now, today, month_start)
    elif role in ('sales_senior_executive', 'sales_executive', 'counsellor', 'tele_caller', 'front_desk'):
        data = _get_sales_dashboard(user, now, today, month_start)
    else:
        data = _get_default_dashboard(user, now, today)

    # Merge common data
    data.update(common_data)
    data['role'] = role
    data['last_updated'] = now.isoformat()

    # Cache for 5 minutes (300s) - balances freshness and performance
    cache.set(cache_key, data, timeout=300)
    return data


def clear_dashboard_cache(user):
    """Clear the cache for a specific user's dashboard."""
    cache_key = _get_cache_key(user)
    cache.delete(cache_key)


def _get_management_dashboard(user, now, today, month_start, thirty_days_ago):
    """Optimized management dashboard with aggregated queries."""
    bq = _branch_filter(user)

    # Single aggregate queries where possible
    student_qs = Student.objects.filter(bq)
    student_agg = student_qs.aggregate(
        total_active=Count('id', filter=Q(status='active')),
        total_inactive=Count('id', filter=Q(status='inactive')),
        new_this_month=Count('id', filter=Q(created_at__gte=month_start)),
    )

    # Attendance aggregate - optimized, no non-existent fields
    att_qs = AttendanceRecord.objects.filter(
        bq, date__gte=month_start.date()
    ).select_related('student', 'batch')
    att_agg = att_qs.aggregate(
        total_records=Count('id'),
        present=Count('id', filter=Q(status__in=['present', 'late'])),
    )
    att_rate = round((att_agg['present'] or 0) / (att_agg['total_records'] or 1) * 100, 2)

    # Fees - optimized with one query using correct status and due computation
    fee_bq = Q()
    if not getattr(user, 'role', None) == 'super_admin':
        bid = getattr(user, 'branch_id', None)
        if bid:
            fee_bq &= Q(student__branch_id=bid)
    fee_agg = StudentFee.objects.filter(fee_bq).aggregate(
        total_collected=Sum('amount_paid'),
        total_due=Sum(
            F('total_amount') - F('discount') - F('amount_paid'),
            filter=Q(status__in=['approval_pending', 'partial', 'overdue']),
            output_field=FloatField()
        ),
        overdue_count=Count('id', filter=Q(status='overdue')),
    )

    # Upcoming exams - limited and optimized
    upcoming_exams = list(
        Exam.objects.filter(
            bq if bq else Q(), is_deleted=False, scheduled_date__gte=today
        ).select_related('batch', 'subject')[:8].values(
            'id', 'title', 'scheduled_date', 'batch__name', 'subject__name', 'exam_type'
        )
    )

    # Leads pipeline
    lead_qs = Lead.objects.filter(bq)
    lead_pipeline = list(
        lead_qs.values('current_stage')
        .annotate(count=Count('id'))
        .order_by('-count')[:10]
    )

    return {
        'kpis': {
            'total_active_students': student_agg['total_active'] or 0,
            'new_admissions': student_agg['new_this_month'] or 0,
            'attendance_rate': att_rate,
            'fee_collected': float(fee_agg['total_collected'] or 0),
            'pending_fees': float(fee_agg['total_due'] or 0),
            'overdue_fees': fee_agg['overdue_count'] or 0,
            'open_leads': lead_qs.exclude(current_stage__in=['converted', 'lost']).count(),
        },
        'upcoming_exams': upcoming_exams,
        'attendance_trend': _get_attendance_trend(bq, 7),  # last 7 days
        'fee_collection_trend': _get_fee_trend(user, 30),
        'lead_pipeline': lead_pipeline,
        'recent_activities': _get_recent_activities(user, 10),
        'charts': {
            'attendance_by_batch': _get_attendance_by_batch(bq),
            'enrollment_by_course': _get_enrollment_by_course(bq),
        }
    }


def _get_faculty_dashboard(user, now, today, month_start):
    """Faculty specific dashboard - my classes, sessions, earnings."""
    try:
        faculty = FacultyProfile.objects.select_related('user').get(user=user)
    except FacultyProfile.DoesNotExist:
        faculty = None

    bq = _branch_filter(user)

    # Today's timetable/sessions
    today_sessions = list(
        # Assuming TimetableSlot or use SessionReport
        SessionReport.objects.filter(
            faculty=faculty, session_date=today
        ).select_related('batch', 'subject')[:5].values(
            'id', 'batch__name', 'subject__name', 'start_time', 'status', 'topics_covered'
        ) if faculty else []
    )

    # My attendance rate - real computation from QR scans (no static)
    my_att_rate = 100.0
    if faculty:
        scan_agg = FacultyQRScanLog.objects.filter(
            faculty=faculty, scanned_at__gte=month_start
        ).aggregate(
            total=Count('id'),
            ontime=Count('id', filter=Q(is_late=False)),
        )
        my_att_rate = round(((scan_agg['ontime'] or 0) / (scan_agg['total'] or 1)) * 100, 2) if scan_agg['total'] else 100.0

    # Pending papers or exams if applicable
    pending_tasks = []
    if user.role in ('paper_checker', 'exam_supervisor'):
        raw_tasks = list(MarkSheet.objects.filter(
            paper_checker=user, is_submitted=False
        ).select_related('student', 'exam')[:5].values(
            'id', 'student__first_name', 'student__surname', 'exam__title'
        ))
        pending_tasks = [
            {
                'id': t['id'],
                'student_name': f"{t.get('student__first_name', '')} {t.get('student__surname', '')}".strip(),
                'exam_title': t.get('exam__title', '')
            }
            for t in raw_tasks
        ]

    # Payroll summary - real from PaySlip (no static/demo)
    payroll_summary = {'this_month': 0.0, 'pending': 0.0}
    if faculty:
        latest_payslip = PaySlip.objects.filter(faculty=faculty).order_by(
            '-payroll_run__year', '-payroll_run__month'
        ).first()
        if latest_payslip:
            payroll_summary = {
                'this_month': float(latest_payslip.net_salary or 0),
                'pending': float(getattr(latest_payslip, 'late_penalty', 0) or 0),
            }

    # Real avg session completion (proxy for rating/quality from SessionReport)
    avg_completion = 0.0
    if faculty:
        comp_agg = SessionReport.objects.filter(
            faculty=faculty, session_date__gte=month_start.date()
        ).aggregate(avg_comp=Avg('completion_percentage'))
        avg_completion = round(float(comp_agg.get('avg_comp') or 0), 1)

    return {
        'kpis': {
            'today_sessions': len(today_sessions),
            'monthly_sessions': SessionReport.objects.filter(
                faculty=faculty, session_date__gte=month_start.date()
            ).count() if faculty else 0,
            'attendance_rate': my_att_rate,
            'pending_tasks': len(pending_tasks),
            'avg_session_completion': avg_completion,
        },
        'today_schedule': today_sessions,
        'pending_tasks': pending_tasks,
        'recent_sessions': list(
            SessionReport.objects.filter(faculty=faculty)
            .select_related('batch', 'subject')
            .order_by('-session_date')[:5]
            .values('id', 'session_date', 'subject__name', 'batch__name', 'completion_percentage', 'status')
        ) if faculty else [],
        'payroll_summary': payroll_summary,
        'charts': {
            'my_attendance_trend': _get_simple_trend(7, bq),
        }
    }


def _get_student_dashboard(user, now, today, month_start):
    """Student/parent specific - personalized, fast loading. Uses real queries only."""
    # For parents, use ParentLink (preferred over linked_student for accuracy)
    student = None
    if user.role == 'parents':
        parent_link = ParentLink.objects.select_related('student__batch', 'student__user').filter(
            parent=user
        ).first()
        if parent_link:
            student = parent_link.student
    else:
        try:
            student = Student.objects.select_related('user', 'batch').get(user=user)
        except Student.DoesNotExist:
            student = None

    if not student:
        return {'kpis': {}, 'message': 'No student profile linked'}

    # Only self data
    bq = Q(id=student.id)

    # Optimized personal stats (no non-existent 'percentage' field on AttendanceRecord)
    attendance = AttendanceRecord.objects.filter(student=student).aggregate(
        total=Count('id'),
        present=Count('id', filter=Q(status__in=['present', 'late'])),
    )
    att_rate = round((attendance['present'] or 0) / (attendance['total'] or 1) * 100, 2)

    # Fees due - use amount_due logic
    fees_due = StudentFee.objects.filter(
        student=student, status__in=['approval_pending', 'partial', 'overdue']
    ).aggregate(
        total_due=Sum(F('total_amount') - F('discount') - F('amount_paid'), output_field=FloatField()),
        count=Count('id')
    )

    # Upcoming exams for my batch
    upcoming = list(
        Exam.objects.filter(
            batch=student.batch, scheduled_date__gte=today, is_deleted=False
        ).select_related('subject')[:5].values(
            'id', 'title', 'scheduled_date', 'subject__name', 'exam_type'
        )
    )

    # Recent results - use PublishedResult (has percentage, total_marks, marks_obtained; no 'grade')
    recent_results = list(
        PublishedResult.objects.filter(student=student)
        .select_related('exam')
        .order_by('-published_at')[:5]
        .values('id', 'exam__title', 'marks_obtained', 'total_marks', 'percentage', 'is_pass', 'rank')
    )

    return {
        'kpis': {
            'attendance_rate': att_rate,
            'fees_due': float(fees_due.get('total_due') or 0),
            'upcoming_exams_count': len(upcoming),
            'avg_score': round(
                float(PublishedResult.objects.filter(student=student).aggregate(
                    avg_p=Avg('percentage')
                )['avg_p'] or 0), 2
            ),
        },
        'upcoming_exams': upcoming,
        'recent_results': recent_results,
        'timetable': _get_student_timetable(student),
        'fee_details': {
            'due_count': fees_due.get('count') or 0,
            'next_due_date': None,
        },
        'charts': {
            'my_performance': _get_student_performance_trend(student),
        }
    }


def _get_sales_dashboard(user, now, today, month_start):
    """Sales, counsellor, telecaller focused on leads and conversions."""
    bq = _branch_filter(user)

    lead_qs = Lead.objects.filter(bq)
    lead_agg = lead_qs.aggregate(
        total_leads=Count('id'),
        new_leads=Count('id', filter=Q(created_at__gte=month_start)),
        converted=Count('id', filter=Q(current_stage='converted')),
    )

    pipeline = list(
        lead_qs.values('current_stage', 'reference')
        .annotate(count=Count('id'))
        .order_by('-count')
    )

    recent_leads = list(
        lead_qs.select_related('assigned_to').order_by('-created_at')[:10].values(
            'id', 'first_name', 'surname', 'phone_student', 'current_stage', 'reference',
            'assigned_to__name', 'created_at'
        )
    )

    return {
        'kpis': {
            'total_leads': lead_agg['total_leads'] or 0,
            'new_leads_this_month': lead_agg['new_leads'] or 0,
            'conversion_rate': round((lead_agg['converted'] or 0) / (lead_agg['total_leads'] or 1) * 100, 2),
            'active_leads': lead_qs.exclude(current_stage__in=['converted', 'lost']).count(),
        },
        'pipeline': pipeline,
        'recent_leads': recent_leads,
        'conversion_trend': _get_simple_trend(30, bq),
        'top_sources': list(lead_qs.values('reference').annotate(count=Count('id')).order_by('-count')[:5]),
    }


def _get_default_dashboard(user, now, today):
    """Fallback."""
    return {
        'kpis': {'message': 'Dashboard ready for your role'},
        'recent_notifications': [],
    }


# Helper functions for trends and charts - cached where possible
def _get_attendance_trend(bq, days=7):
    """Optimized trend query."""
    dates = []
    rates = []
    for i in range(days):
        d = (timezone.now() - timedelta(days=i)).date()
        att = AttendanceRecord.objects.filter(
            bq, date=d
        ).aggregate(
            present=Count('id', filter=Q(status__in=['present', 'late'])),
            total=Count('id'),
        )
        rate = round((att['present'] or 0) / (att['total'] or 1) * 100, 1) if att['total'] else 0
        dates.append(d.isoformat())
        rates.append(rate)
    return {'dates': dates[::-1], 'rates': rates[::-1]}


def _get_fee_trend(user=None, days=30):
    """Real fee collection trend using verified Payments grouped by ISO week (no static data)."""
    from collections import defaultdict
    weekly = defaultdict(float)
    start_date = (timezone.now() - timedelta(days=days)).date()
    q = Q(payment_date__gte=start_date, status='verified')
    if user and getattr(user, 'role', None) != 'super_admin':
        bid = getattr(user, 'branch_id', None)
        if bid:
            q &= Q(student__branch_id=bid)
        elif hasattr(user, 'organization') and user.organization:
            q &= Q(student__branch__organization=user.organization)
    payments = Payment.objects.filter(q)
    for p in payments.iterator():  # memory efficient
        week_key = p.payment_date.isocalendar()[1]
        weekly[week_key] += float(p.amount or 0)
    sorted_weeks = sorted(weekly.keys())[-4:]
    labels = [f'W{w}' for w in sorted_weeks] or ['W1', 'W2', 'W3', 'W4']
    values = [weekly[w] for w in sorted_weeks] or [0.0] * 4
    return {'labels': labels, 'values': values}


def _get_attendance_by_batch(bq):
    """Batch wise attendance."""
    data = list(
        AttendanceRecord.objects.filter(bq).values('batch__name')
        .annotate(
            total=Count('id'),
            present=Count('id', filter=Q(status__in=['present', 'late']))
        ).order_by('batch__name')[:10]
    )
    return [
        {
            'batch': item['batch__name'] or 'Unknown',
            'rate': round((item['present'] / (item['total'] or 1)) * 100, 1)
        } for item in data if item['total']
    ]


def _get_enrollment_by_course(bq):
    """Real enrollment by course using Student model (no static data)."""
    data = list(
        Student.objects.filter(bq).values('course')
        .annotate(count=Count('id'))
        .order_by('-count')[:5]
    )
    return [
        {'course': item.get('course', 'Unknown') or 'Unknown', 'count': item['count']}
        for item in data
    ] or []


def _get_recent_activities(user, limit=10):
    """Recent activities from audit or notifications."""
    return list(
        NotificationHistory.objects.filter(user=user)
        .order_by('-created_at')[:limit]
        .values('title', 'body', 'created_at')
    )


def _get_simple_trend(days=7, bq=None):
    """Real generic trend using daily AttendanceRecord counts (no demo/static data)."""
    dates = []
    values = []
    for i in range(days - 1, -1, -1):
        d = (timezone.now() - timedelta(days=i)).date()
        qs = AttendanceRecord.objects.filter(date=d)
        if bq:
            qs = qs.filter(bq)
        count = qs.count()
        dates.append(d.isoformat())
        values.append(count)
    return {'labels': dates, 'values': values}


def _get_student_timetable(student):
    """Real student timetable from TimetableSlot (no static data)."""
    if not student or not student.batch:
        return []
    slots = list(
        TimetableSlot.objects.filter(
            batch=student.batch, is_recurring=True
        ).select_related('subject', 'faculty__user', 'classroom')
        .order_by('day_of_week', 'start_time')[:10]
        .values(
            'day_of_week', 'start_time', 'end_time',
            'subject__name', 'faculty__user__name', 'session_type'
        )
    )
    day_map = {0: 'Monday', 1: 'Tuesday', 2: 'Wednesday', 3: 'Thursday',
               4: 'Friday', 5: 'Saturday', 6: 'Sunday'}
    return [
        {
            'day': day_map.get(s.get('day_of_week'), 'N/A'),
            'subject': s.get('subject__name', 'N/A'),
            'time': f"{s.get('start_time', '')}-{s.get('end_time', '')}",
            'faculty': s.get('faculty__user__name', 'N/A'),
            'type': s.get('session_type', 'regular')
        }
        for s in slots
    ]


def _get_student_performance_trend(student):
    """Real performance trend from PublishedResult by subject (no static data)."""
    if not student:
        return {'subjects': [], 'scores': []}
    perf = list(
        PublishedResult.objects.filter(student=student)
        .select_related('exam__subject')
        .values('exam__subject__name')
        .annotate(avg_score=Avg('percentage'))
        .order_by('exam__subject__name')[:6]
    )
    return {
        'subjects': [p.get('exam__subject__name', 'Unknown') for p in perf],
        'scores': [round(float(p.get('avg_score', 0)), 1) for p in perf],
    }
