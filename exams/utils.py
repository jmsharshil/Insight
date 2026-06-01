import uuid
import math
import logging
from datetime import timedelta
from django.utils import timezone

logger = logging.getLogger(__name__)


# ── Stub notification helper ──────────────────────────────────────────────────

def notify(recipient_user_id, title, body, metadata=None):
    """Stub: push/in-app notification. Replace with real implementation."""
    logger.info(f"NOTIFY [{recipient_user_id}] {title}: {body}")


def auto_grade_mcq(session_id):
    """
    Auto-grade MCQ exam. Returns (marks_obtained, percentage, is_pass).

    Respects exam.result_release_mode:
      "instant" → create MarkSheet + PublishedResult immediately
      "manual"  → create MarkSheet only, admin publishes later
    """
    from .models import ExamSession, StudentAnswer
    from results.models import MarkSheet, PublishedResult

    session = ExamSession.objects.select_related('exam').get(id=session_id)
    exam = session.exam
    answers = StudentAnswer.objects.filter(session=session).select_related('selected_choice', 'question')

    marks = 0
    for ans in answers:
        if ans.selected_choice and ans.selected_choice.is_correct:
            marks += ans.question.marks

    pct = round((marks / exam.total_marks) * 100, 2) if exam.total_marks > 0 else 0
    passed = marks >= exam.pass_marks

    MarkSheet.objects.update_or_create(
        exam=exam, student=session.student,
        defaults={'marks_obtained': marks, 'is_pass': passed, 'checked_at': timezone.now(), 'is_submitted': True},
    )

    if exam.result_release_mode == 'instant':
        PublishedResult.objects.update_or_create(
            exam=exam, student=session.student,
            defaults={'marks_obtained': marks, 'total_marks': exam.total_marks, 'percentage': pct, 'is_pass': passed},
        )

    return marks, pct, passed


def auto_submit_session(session):
    """Force-submit a session (timeout or violation)."""
    from .models import Question

    session.is_submitted = True
    session.auto_submitted = True
    session.submitted_at = timezone.now()
    session.save(update_fields=['is_submitted', 'auto_submitted', 'submitted_at'])

    exam = session.exam
    has_subjective = Question.objects.filter(exam=exam, question_type='subjective').exists()

    if not has_subjective:
        auto_grade_mcq(session.id)
    else:
        from results.models import MarkSheet
        MarkSheet.objects.get_or_create(exam=exam, student=session.student)

    return session


def assign_papers_to_checker(exam_id, checker_ids):
    """
    Distribute unassigned marksheets round-robin across checkers.
    FRD §4.6.2: send email + in-app notification to each checker.
    """
    from results.models import MarkSheet
    from .models import Exam
    from .emails import send_checker_assignment_email

    if not checker_ids:
        return

    exam = Exam.objects.get(id=exam_id)
    sheets = MarkSheet.objects.filter(exam_id=exam_id, paper_checker__isnull=True)
    for i, sheet in enumerate(sheets):
        checker_id = checker_ids[i % len(checker_ids)]
        sheet.paper_checker_id = checker_id
        sheet.save(update_fields=['paper_checker_id'])
        generate_checker_token(sheet)
        send_checker_assignment_email(sheet)
        # v2: in-app notification stub (FRD §4.6.2)
        notify(
            checker_id,
            title="Paper assigned",
            body=f"You have been assigned papers for {exam.title}",
            metadata={"exam_id": str(exam_id), "marksheet_id": str(sheet.id)},
        )


def calculate_ranks(exam_id):
    """Assign competition ranking (1,2,2,4) by marks DESC."""
    from results.models import PublishedResult

    results = list(PublishedResult.objects.filter(exam_id=exam_id).order_by('-marks_obtained'))
    if not results:
        return

    rank = 1
    for i, r in enumerate(results):
        if i > 0 and r.marks_obtained < results[i - 1].marks_obtained:
            rank = i + 1
        r.rank = rank
    PublishedResult.objects.bulk_update(results, ['rank'])


def check_geo_boundary(exam, student_lat, student_lon):
    """Haversine check. Returns (is_allowed, distance_meters)."""
    if exam.geo_radius_meters == 0:
        return True, 0.0

    R = 6371000
    lat1, lat2 = math.radians(float(exam.geo_lat)), math.radians(float(student_lat))
    dlat = math.radians(float(student_lat) - float(exam.geo_lat))
    dlon = math.radians(float(student_lon) - float(exam.geo_lon))
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    distance = R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return distance <= exam.geo_radius_meters, round(distance, 2)


def generate_checker_token(marksheet):
    """Create a CheckerToken valid for 72 hours."""
    from .models import CheckerToken
    token_str = str(uuid.uuid4())
    CheckerToken.objects.create(
        marksheet=marksheet, token=token_str,
        expires_at=timezone.now() + timedelta(hours=72),
    )
    return token_str
