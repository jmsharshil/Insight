"""Exam / student performance report service."""
from django.db.models import Count, Avg, Q, F, Max
from results.models import PublishedResult, MarkSheet
from exams.models import Exam


def get_exam_report(user, params):
    role = getattr(user, 'role', None)
    bq = Q()
    org = getattr(user, 'organization', None)
    if org:
        bq &= Q(exam__branch__organization=org)
    if role != 'super_admin':
        bid = getattr(user, 'branch_id', None)
        if bid:
            bq = Q(exam__branch_id=bid)

    branch_id = params.get('branch_id')
    batch_id = params.get('batch_id')
    exam_id = params.get('exam_id')
    subject_id = params.get('subject_id')

    if branch_id:
        bq &= Q(exam__branch_id=branch_id)
    if batch_id:
        bq &= Q(exam__batch_id=batch_id)
    if exam_id:
        bq &= Q(exam_id=exam_id)
    if subject_id:
        bq &= Q(exam__subject_id=subject_id)

    pr_qs = PublishedResult.objects.filter(bq)

    total_results = pr_qs.count()
    pass_count = pr_qs.filter(is_pass=True).count()
    fail_count = pr_qs.filter(is_pass=False).count()

    agg = pr_qs.aggregate(avg_score=Avg('percentage'))
    avg_score = round(agg['avg_score'] or 0, 2)

    # Top scorer
    top = pr_qs.order_by('-percentage', '-marks_obtained').select_related('student').first()
    if top:
        top_scorer = {
            'student_id': top.student_id,
            'student_name': f"{top.student.first_name} {top.student.surname}".strip(),
            'marks': top.marks_obtained,
            'percentage': top.percentage,
        }
    else:
        top_scorer = {'student_id': None, 'student_name': '', 'marks': None, 'percentage': None}

    # Total unique exams
    total_exams = pr_qs.values('exam_id').distinct().count()

    # Subject performance
    subj_perf = list(
        pr_qs.filter(exam__subject__isnull=False)
        .values('exam__subject_id', 'exam__subject__name')
        .annotate(
            average_score=Avg('percentage'),
            total=Count('id'),
            passed=Count('id', filter=Q(is_pass=True)),
        )
        .order_by('exam__subject__name')
    )
    subject_performance = [
        {
            'subject_id': s['exam__subject_id'],
            'subject_name': s['exam__subject__name'] or '',
            'average_score': round(s['average_score'] or 0, 2),
            'pass_rate': round((s['passed'] / (s['total'] or 1)) * 100, 2),
        }
        for s in subj_perf
    ]

    # Student performance (top 100 by avg score)
    student_perf = list(
        pr_qs.values('student_id', 'student__first_name', 'student__surname')
        .annotate(
            total_exams=Count('id'),
            average_score=Avg('percentage'),
            pass_count=Count('id', filter=Q(is_pass=True)),
            fail_count=Count('id', filter=Q(is_pass=False)),
        )
        .order_by('-average_score')[:100]
    )
    student_performance = [
        {
            'student_id': sp['student_id'],
            'student_name': f"{sp['student__first_name']} {sp['student__surname']}".strip(),
            'total_exams': sp['total_exams'],
            'average_score': round(sp['average_score'] or 0, 2),
            'pass_count': sp['pass_count'],
            'fail_count': sp['fail_count'],
        }
        for sp in student_perf
    ]

    return {
        'total_exams': total_exams,
        'pass_count': pass_count,
        'fail_count': fail_count,
        'average_score': avg_score,
        'top_scorer': top_scorer,
        'subject_performance': subject_performance,
        'student_performance': student_performance,
    }
