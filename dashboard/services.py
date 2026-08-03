"""Dashboard services for role-specific, highly optimized KPIs and data.
Uses heavy caching, query optimization (select_related, prefetch_related, aggregates),
and role-based data scoping for minimal response times.
"""
from datetime import timedelta
from django.utils import timezone
from django.db.models import Count, Sum, Q, F, Avg, Case, When, Value, FloatField, Min
from django.core.cache import cache

from auth_user.models import User, NotificationHistory
from students.models import Student, ParentLink
from attendance.models import AttendanceRecord
from fees.models import StudentFee, Payment
from exams.models import Exam
from results.models import MarkSheet, PublishedResult
from leads.models import Lead
from onboarding.models import Admission
from batches.models import Batch, TimetableSlot
from faculty.models import FacultyProfile, SessionReport, FacultyQRScanLog
from payroll.models import PaySlip
from leave.models import LeaveApplication, LeaveBalance, StudentLeaveApplication


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

    # Add leave data for ALL roles (staff, faculty, student, management, sales, etc.)
    leave_summary = _get_leave_dashboard_data(user, role, today, month_start)
    data.update(leave_summary)

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
    
    adm_qs = Admission.objects.filter(bq)
    admissions_other_ref_count = adm_qs.filter(reference='other').count()

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
        total_billed=Sum('total_amount'),
        total_discount=Sum('discount'),
        overdue_count=Count('id', filter=Q(status='overdue')),
    )

    total_billed = float(fee_agg.get('total_billed') or 0)
    total_discount = float(fee_agg.get('total_discount') or 0)
    net_billed = total_billed - total_discount
    
    total_collected = float(fee_agg.get('total_collected') or 0)
    total_due = float(fee_agg.get('total_due') or 0)
    
    collected_pct = round((total_collected / net_billed) * 100, 2) if net_billed > 0 else 0
    due_pct = round((total_due / net_billed) * 100, 2) if net_billed > 0 else 0

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
            'attendance_rate': f"{att_agg.get('present') or 0}/{att_agg.get('total_records') or 0} ({att_rate}%)",
            'fee_collected': f"{total_collected} ({collected_pct}%)",
            'pending_fees': f"{total_due} ({due_pct}%)",
            'overdue_fees': fee_agg['overdue_count'] or 0,
            'open_leads': lead_qs.exclude(current_stage__in=['converted', 'lost']).count(),
            'admissions_other_ref': admissions_other_ref_count,
        },
        'upcoming_exams': upcoming_exams,
        'exam_stats': _get_exam_stats(bq),
        'result_delay_stats': _get_result_delay_stats(bq),
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
    scan_agg = {}
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
            paper_checker=user, is_submitted=False, exam__is_deleted=False
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

    visiting_count = 0
    if faculty and faculty.employment_type != 'full_time':
        qr_dates = set(FacultyQRScanLog.objects.filter(
            faculty=faculty, scanned_at__gte=month_start
        ).dates('scanned_at', 'day'))
        session_dates = set(SessionReport.objects.filter(
            faculty=faculty, session_date__gte=month_start.date()
        ).values_list('session_date', flat=True))
        visiting_count = len(qr_dates | session_dates)

    return {
        'kpis': {
            'today_sessions': len(today_sessions),
            'monthly_sessions': SessionReport.objects.filter(
                faculty=faculty, session_date__gte=month_start.date()
            ).count() if faculty else 0,
            'attendance_rate': f"{scan_agg.get('ontime') or 0}/{scan_agg.get('total') or 0} ({my_att_rate}%)",
            'pending_tasks': len(pending_tasks),
            'avg_session_completion': f"{avg_completion}%",
            'visiting_count': visiting_count,
        },
        'today_schedule': today_sessions,
        'pending_tasks': pending_tasks,
        'exam_performance': _get_faculty_exam_performance(user, faculty),
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
        # Prefer is_primary=True per ParentLink architecture (consistent with ParentStudentProfileAPIView)
        parent_link = ParentLink.objects.select_related('student__batch', 'student__user').filter(
            parent=user, is_primary=True
        ).first()
        if not parent_link:
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

    # Exam attendance rate - exclude deleted exams
    exam_attendance = MarkSheet.objects.filter(
        student=student, exam__is_deleted=False
    ).aggregate(
        total=Count('id'),
        present=Count('id', filter=Q(is_absent=False))
    )
    exam_att_rate = round((exam_attendance['present'] or 0) / (exam_attendance['total'] or 1) * 100, 2)

    # Fees due - use amount_due logic
    fees_due = StudentFee.objects.filter(
        student=student, status__in=['approval_pending', 'partial', 'overdue']
    ).aggregate(
        total_due=Sum(F('total_amount') - F('discount') - F('amount_paid'), output_field=FloatField()),
        count=Count('id')
    )
        
    from fees.models import InstallmentItem
    pending_installments = list(
        InstallmentItem.objects.filter(
            plan__student_fee__student=student, is_paid=False
        ).order_by('due_date')[:5]
        .values('id', 'amount', 'due_date', 'plan__student_fee__fee_structure__name')
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
    # Exclude soft-deleted exams per consistency requirement for dashboards/summary APIs
    recent_results = list(
        PublishedResult.objects.filter(
            student=student, exam__is_deleted=False
        )
        .select_related('exam')
        .order_by('-published_at')[:5]
        .values('id', 'exam__title', 'marks_obtained', 'total_marks', 'percentage', 'is_pass', 'rank')
    )

    # Enrich recent_results with percentile for each result
    for result in recent_results:
        try:
            exam_id = result.get('exam_id') or PublishedResult.objects.filter(
                student=student, id=result['id']
            ).values_list('exam_id', flat=True).first()
            if exam_id:
                total = PublishedResult.objects.filter(exam_id=exam_id).count()
                if total > 0 and result.get('marks_obtained') is not None:
                    at_or_below = PublishedResult.objects.filter(
                        exam_id=exam_id, marks_obtained__lte=result['marks_obtained']
                    ).count()
                    result['percentile'] = round(at_or_below / total * 100, 2)
                else:
                    result['percentile'] = None
            else:
                result['percentile'] = None
        except Exception:
            result['percentile'] = None

    avg_score = round(
        float(PublishedResult.objects.filter(
            student=student, exam__is_deleted=False
        ).aggregate(
            avg_p=Avg('percentage')
        )['avg_p'] or 0), 2
    )

    return {
        'kpis': {
            'attendance_rate': f"{attendance.get('present') or 0}/{attendance.get('total') or 0} ({att_rate}%)",
            'exam_attendance': f"{exam_attendance.get('present') or 0}/{exam_attendance.get('total') or 0} ({exam_att_rate}%)",
            'fees_due': float(fees_due.get('total_due') or 0),
            'upcoming_exams_count': len(upcoming),
            'avg_score': f"{avg_score}%",
        },
        'upcoming_exams': upcoming,
        'recent_results': recent_results,
        'timetable': _get_student_timetable(student),
        'fee_details': {
            'due_count': fees_due.get('count') or 0,
            'next_due_date': pending_installments[0]['due_date'] if pending_installments else None,
            'pending_installments': pending_installments,
        },
        'charts': {
            'my_performance': _get_student_performance_trend(student),
        }
    }


def _get_sales_dashboard(user, now, today, month_start):
    """Sales, counsellor, telecaller focused on leads and conversions."""
    bq = _branch_filter(user)

    lead_qs = Lead.objects.filter(bq)

    # Junior sales roles only see leads assigned to them.
    # Senior roles (sales_senior_executive) see all branch leads.
    individual_roles = ('sales_executive', 'tele_caller', 'counsellor', 'front_desk')
    if user.role in individual_roles:
        lead_qs = lead_qs.filter(assigned_to=user)

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
            'conversion_rate': f"{lead_agg.get('converted') or 0}/{lead_agg.get('total_leads') or 0} ({round((lead_agg.get('converted') or 0) / (lead_agg.get('total_leads') or 1) * 100, 2)}%)",
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


def _get_leave_dashboard_data(user, role, today, month_start):
    """Leave data integrated for ALL roles in dashboard.
    - Management: team pending leaves, staff on leave today
    - Staff/Faculty: personal leave balances, pending applications, recent leaves
    - Students/Parents: student leave applications status
    - Sales: personal leave summary
    Optimized with aggregates and limited querysets.
    """
    leave_data = {
        'pending_count': 0,
        'recent_leaves': [],
        'balances': [],
        'type': 'staff',
    }

    if role in ('student', 'parents'):
        # Student/parent leave data using StudentLeaveApplication.
        # Uses `parent_consulted` (per model constraint) to distinguish flows:
        # - parent_consulted=False + pending → Parent Approval Pending (for parents)
        # - parent_consulted=True + pending → Admin Approval Pending
        student = None
        if role == 'parents':
            try:
                parent_link = ParentLink.objects.select_related('student').filter(
                    parent=user, is_primary=True
                ).first()
                if not parent_link:
                    parent_link = ParentLink.objects.select_related('student').filter(
                        parent=user
                    ).first()
                if parent_link:
                    student = parent_link.student
            except Exception:
                pass
        else:
            try:
                student = Student.objects.select_related('user').get(user=user)
            except Student.DoesNotExist:
                pass

        if student:
            student_leaves_qs = StudentLeaveApplication.objects.filter(student=student)
            # Role-specific pending count (what the user needs to act on)
            if role == 'parents':
                # Parents only care about leaves needing their approval
                pending_qs = student_leaves_qs.filter(
                    status='pending', parent_consulted=False
                )
            else:
                # Students see all their pending leaves
                pending_qs = student_leaves_qs.filter(status='pending')
            leave_data['pending_count'] = pending_qs.count()

            recent_list = list(
                student_leaves_qs.order_by('-created_at')[:5].values(
                    'id', 'leave_type', 'from_date', 'to_date', 'status',
                    'reason', 'parent_consulted', 'parent_signature_date', 'created_at'
                )
            )
            # Compute status_display using parent_consulted (matches serializer logic)
            for leave in recent_list:
                if leave.get('status') == 'pending':
                    if not leave.get('parent_consulted', True):
                        leave['status_display'] = 'Parent Approval Pending'
                    else:
                        leave['status_display'] = 'Admin Approval Pending'
                else:
                    leave['status_display'] = leave.get('status', '').replace('_', ' ').title()
            leave_data['recent_leaves'] = recent_list
            leave_data['type'] = 'student'
        else:
            leave_data['message'] = 'No student profile linked for leave data'
    else:
        # Staff, faculty, management, sales roles - use staff Leave models
        # Personal leave balances
        balances_qs = LeaveBalance.objects.filter(
            user=user, year=today.year
        )
        if balances_qs.exists():
            balances = list(balances_qs.values(
                'leave_type', 'total_days', 'used_days', 'carried_forward'
            ))
            leave_data['balances'] = [
                {
                    'leave_type': b['leave_type'],
                    'total': float(b['total_days']),
                    'used': float(b['used_days']),
                    'carried_forward': float(b['carried_forward']),
                    'remaining': float(b['total_days'] + b['carried_forward'] - b['used_days']),
                } for b in balances
            ]
            leave_data['total_remaining_days'] = sum(b['remaining'] for b in leave_data['balances'])
        else:
            leave_data['balances'] = []
            leave_data['total_remaining_days'] = 0.0

        # Personal pending and recent leaves
        my_leaves_qs = LeaveApplication.objects.filter(applied_by=user)
        leave_data['pending_count'] = my_leaves_qs.filter(status='approval_pending').count()
        leave_data['recent_leaves'] = list(
            my_leaves_qs.order_by('-created_at')[:5].values(
                'id', 'leave_type', 'from_date', 'to_date', 'status',
                'total_days', 'reason', 'created_at'
            )
        )
        leave_data['type'] = 'staff'

        # For management/admin roles - add team-wide leave insights
        if role in ('super_admin', 'branch_manager', 'admin_senior_executive',
                   'admin_executive', 'accountant'):
            bq = _branch_filter(user, LeaveApplication)
            # Team pending approvals (all staff leaves pending)
            leave_data['team_pending'] = LeaveApplication.objects.filter(
                bq, status='approval_pending'
            ).count()

            # Student leaves pending - uses parent_consulted internally for workflow stages
            # (admins see all pending regardless of parent step)
            student_bq = Q(status='pending')
            if role != 'super_admin':
                bid = getattr(user, 'branch_id', None)
                if bid:
                    student_bq &= Q(student__branch_id=bid)
            leave_data['student_pending'] = StudentLeaveApplication.objects.filter(
                student_bq
            ).count()
            leave_data['total_pending'] = (
                leave_data.get('team_pending', 0) + leave_data.get('student_pending', 0)
            )

            # Staff currently on leave today
            leave_data['team_on_leave_today'] = LeaveApplication.objects.filter(
                bq,
                status='approved',
                from_date__lte=today,
                to_date__gte=today
            ).count()

            # Team recent leaves (limited)
            leave_data['team_recent_leaves'] = list(
                LeaveApplication.objects.filter(bq)
                .select_related('applied_by')
                .order_by('-created_at')[:5]
                .values(
                    'id', 'applied_by__name', 'leave_type', 'from_date',
                    'to_date', 'status', 'total_days'
                )
            )

    return {'leave': leave_data}


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
    """Real student timetable from TimetableSlot (no static data).
    Returns slots starting from today's day of week through the rest of the week.
    On Sunday it wraps around (Sun → Sat).
    """
    if not student or not student.batch:
        return []

    # Django's weekday(): Monday=0 … Sunday=6
    # TimetableSlot day_of_week: 0=Monday … 6=Sunday (same convention)
    today_dow = timezone.now().weekday()  # 0=Mon … 6=Sun

    # Build ordered list of day_of_week values starting from today
    if today_dow == 6:  # Sunday → show Sun(6), Mon(0)…Sat(5)
        ordered_days = [6, 0, 1, 2, 3, 4, 5]
    else:              # e.g. Wednesday(2) → [2, 3, 4, 5, 6]
        ordered_days = list(range(today_dow, 7))

    slots = list(
        TimetableSlot.objects.filter(
            batch=student.batch, is_recurring=True,
            day_of_week__in=ordered_days,
        ).select_related('subject', 'faculty__user', 'classroom')
        .order_by('day_of_week', 'start_time')
        .values(
            'day_of_week', 'start_time', 'end_time',
            'subject__name', 'faculty__user__name', 'session_type'
        )
    )

    # Re-sort so they follow the ordered_days sequence (not simple numeric order)
    day_order = {d: i for i, d in enumerate(ordered_days)}
    slots.sort(key=lambda s: (day_order.get(s['day_of_week'], 99), str(s['start_time'])))

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
        PublishedResult.objects.filter(student=student, exam__is_deleted=False)
        .select_related('exam__subject')
        .values('exam__subject__name')
        .annotate(avg_score=Avg('percentage'))
        .order_by('exam__subject__name')[:6]
    )
    return {
        'subjects': [p.get('exam__subject__name', 'Unknown') for p in perf],
        'scores': [round(float(p.get('avg_score', 0)), 1) for p in perf],
    }


def _get_exam_stats(bq):
    """Compute aggregate exam statistics for management dashboard.
    Returns avg attendance %, avg pass %, and avg result % across recent exams.
    """
    from students.models import Student
    # Recent completed/published exams (last 20 for performance)
    recent_exams = Exam.objects.filter(
        bq if bq else Q(),
        is_deleted=False,
        status__in=['completed', 'results_published'],
    ).select_related('batch').order_by('-scheduled_date')[:20]

    attendance_rates = []
    for exam in recent_exams:
        if not exam.batch_id:
            continue
        total_enrolled = Student.objects.filter(
            batch_id=exam.batch_id, status='active'
        ).count()
        if total_enrolled == 0:
            continue
        total_attended = MarkSheet.objects.filter(
            exam=exam, is_absent=False
        ).count()
        attendance_rates.append(round(total_attended / total_enrolled * 100, 2))

    # Pass rate and avg percentage from published results
    pr_bq = Q()
    if bq and bq.children:
        for child in bq.children:
            if isinstance(child, tuple):
                key, val = child
                if key.startswith('branch'):
                    pr_bq &= Q(**{f"exam__{key}": val})
                else:
                    pr_bq &= Q(**{key: val})

    pr_agg = PublishedResult.objects.filter(
        pr_bq, exam__is_deleted=False,
    ).aggregate(
        total=Count('id'),
        passed=Count('id', filter=Q(is_pass=True)),
        avg_percentage=Avg('percentage'),
        exempt_count=Count('id', filter=Q(percentage__gte=60)),
        aggregate_count=Count('id', filter=Q(percentage__gte=50, percentage__lt=60)),
        pass_count=Count('id', filter=Q(percentage__gte=40, percentage__lt=50)),
        fail_count=Count('id', filter=Q(percentage__lt=40)),
    )
    total_results = pr_agg.get('total') or 0
    pass_pct = round((pr_agg.get('passed') or 0) / max(total_results, 1) * 100, 2)

    # Absent count across all recent exams (recent_exams already excludes deleted)
    total_absent = MarkSheet.objects.filter(
        exam__in=recent_exams, is_absent=True
    ).count()
    total_marksheets = MarkSheet.objects.filter(exam__in=recent_exams).count()
    absent_pct = round(total_absent / max(total_marksheets, 1) * 100, 2)

    exempt_c = pr_agg.get('exempt_count') or 0
    aggregate_c = pr_agg.get('aggregate_count') or 0
    pass_c = pr_agg.get('pass_count') or 0
    fail_c = pr_agg.get('fail_count') or 0

    return {
        'avg_exam_attendance_pct': round(
            sum(attendance_rates) / len(attendance_rates), 2
        ) if attendance_rates else None,
        'avg_pass_percentage': pass_pct,
        'avg_result_percentage': round(float(pr_agg.get('avg_percentage') or 0), 2),
        'total_exams_completed': len(list(recent_exams)),
        'total_published_results': total_results,
        'grade_distribution': {
            'exempt': {
                'count': exempt_c,
                'percentage': round(exempt_c / max(total_results, 1) * 100, 2),
                'label': 'Exempt (60%+)',
            },
            'aggregate': {
                'count': aggregate_c,
                'percentage': round(aggregate_c / max(total_results, 1) * 100, 2),
                'label': 'Aggregate (50–60%)',
            },
            'pass': {
                'count': pass_c,
                'percentage': round(pass_c / max(total_results, 1) * 100, 2),
                'label': 'Pass (40–50%)',
            },
            'fail': {
                'count': fail_c,
                'percentage': round(fail_c / max(total_results, 1) * 100, 2),
                'label': 'Fail (<40%)',
            },
            'absent': {
                'count': total_absent,
                'percentage': absent_pct,
                'label': 'Absent',
            },
        },
    }


def _get_faculty_exam_performance(user, faculty):
    """Exam performance stats for faculty dashboard.
    Returns attendance %, pass %, avg percentage for exams assigned to this faculty.
    """
    from students.models import Student
    if not faculty:
        return {'exams': [], 'summary': {}}

    # Exams for this faculty (completed/published)
    exams = Exam.objects.filter(
        faculty=faculty,
        is_deleted=False,
        status__in=['completed', 'results_published'],
    ).select_related('batch', 'subject').order_by('-scheduled_date')[:10]

    exam_data = []
    for exam in exams:
        total_enrolled = 0
        attendance_pct = None
        if exam.batch_id:
            total_enrolled = Student.objects.filter(
                batch_id=exam.batch_id, status='active'
            ).count()
            if total_enrolled > 0:
                total_attended = MarkSheet.objects.filter(
                    exam=exam, is_absent=False
                ).count()
                attendance_pct = round(total_attended / total_enrolled * 100, 2)

        # Result stats from published results
        pr_agg = PublishedResult.objects.filter(exam=exam).aggregate(
            total=Count('id'),
            passed=Count('id', filter=Q(is_pass=True)),
            avg_pct=Avg('percentage'),
        )
        total_pr = pr_agg.get('total') or 0
        pass_pct = round((pr_agg.get('passed') or 0) / max(total_pr, 1) * 100, 2)

        exam_data.append({
            'exam_id': str(exam.id),
            'title': exam.title,
            'subject': exam.subject.name if exam.subject else None,
            'batch': exam.batch.name if exam.batch else None,
            'scheduled_date': exam.scheduled_date.isoformat() if exam.scheduled_date else None,
            'attendance_percentage': attendance_pct,
            'pass_percentage': pass_pct,
            'avg_result_percentage': round(float(pr_agg.get('avg_pct') or 0), 2),
            'total_students': total_pr,
        })

    # Summary across all faculty exams - exclude deleted
    all_pr = PublishedResult.objects.filter(
        exam__faculty=faculty,
        exam__status__in=['completed', 'results_published'],
        exam__is_deleted=False,
    ).aggregate(
        total=Count('id'),
        passed=Count('id', filter=Q(is_pass=True)),
        avg_pct=Avg('percentage'),
    )
    total_all = all_pr.get('total') or 0

    return {
        'exams': exam_data,
        'summary': {
            'total_exams': len(exam_data),
            'overall_pass_percentage': round(
                (all_pr.get('passed') or 0) / max(total_all, 1) * 100, 2
            ),
            'overall_avg_percentage': round(float(all_pr.get('avg_pct') or 0), 2),
            'total_students_evaluated': total_all,
        }
    }


def _get_result_delay_stats(bq):
    """Compute simple high-level result delay stats for the dashboard."""
    qs = Exam.objects.filter(
        bq if bq else Q(), is_deleted=False
    ).exclude(status='draft').order_by('-scheduled_date')[:50]
    
    total = qs.count()
    if total == 0:
        return {'total': 0, 'on_time': 0, 'late': 0, 'pending': 0}

    on_time = 0
    late = 0
    pending = 0

    for exam in qs:
        expected_completion = exam.scheduled_date + timedelta(days=7)
        if exam.status != 'results_published':
            if expected_completion < timezone.now().date():
                late += 1
            else:
                pending += 1
        else:
            first_pub = exam.published_results.aggregate(Min('published_at'))['published_at__min']
            if first_pub:
                if first_pub.date() > expected_completion:
                    late += 1
                else:
                    on_time += 1
            else:
                pending += 1
                
    return {
        'total': total,
        'on_time': on_time,
        'late': late,
        'pending': pending
    }
