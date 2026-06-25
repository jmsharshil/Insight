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
        assign_papers_to_checker(exam.id)

    return session


def get_available_paper_checkers(exam):
    """
    Returns list of paper_checker User IDs available in the exam's time slot.
    Matches against exam.paper_checkers (M2M) and checks time overlap with
    user's work_start_time / work_end_time on the scheduled_date.
    """
    from .models import Exam
    from django.contrib.auth import get_user_model
    User = get_user_model()

    if not isinstance(exam, Exam):
        exam = Exam.objects.select_related().prefetch_related('paper_checkers').get(id=exam)

    if not exam.paper_checkers.exists():
        logger.warning(f"No paper_checkers configured for exam {exam.id}")
        if exam.faculty and getattr(exam.faculty.user, 'is_active', True):
            return [exam.faculty.user.id]
        if exam.created_by:
            return [exam.created_by.id]
        return []

    # Get all possible checkers for this exam
    checkers = list(exam.paper_checkers.all())

    available = []
    exam_start = exam.start_time
    exam_end = exam.end_time
    exam_date = exam.scheduled_date

    for checker in checkers:
        # Skip inactive
        if not getattr(checker, 'is_active', True):
            continue

        work_start = getattr(checker, 'work_start_time', None)
        work_end = getattr(checker, 'work_end_time', None)

        # If no work times set, assume available (fallback)
        if not work_start or not work_end:
            available.append(checker.id)
            continue

        # Check time slot overlap (simple overlap logic)
        # Available if checker's work period overlaps with exam period
        if (work_start <= exam_end and work_end >= exam_start):
            available.append(checker.id)
        else:
            logger.info(f"Checker {checker.id} unavailable for exam time slot "
                       f"({exam_start}-{exam_end} vs their {work_start}-{work_end})")

    logger.info(f"Available paper checkers for exam {exam.id}: {len(available)}/{len(checkers)}")
    return available


def assign_papers_to_checker(exam_id, checker_ids=None):
    """
    Auto-assign or distribute unassigned marksheets round-robin to paper checkers.
    If checker_ids not provided, auto-selects from exam.paper_checkers using
    get_available_paper_checkers() based on exam's time slot.
    FRD §4.6.2: send email + in-app notification to each checker.
    """
    from results.models import MarkSheet
    from .models import Exam
    from .emails import send_checker_assignment_email

    exam = Exam.objects.get(id=exam_id)

    if not checker_ids:
        # Auto-assign from available in time slot
        checker_ids = get_available_paper_checkers(exam)
        if not checker_ids:
            logger.error(f"No available paper checkers for exam {exam_id}. "
                        "Please configure paper_checkers on Exam and ensure time slot availability.")
            return 0
        else:
            exam.paper_checkers.add(*checker_ids)

    sheets = MarkSheet.objects.filter(exam_id=exam_id, paper_checker__isnull=True)
    if not sheets.exists():
        logger.info(f"No unassigned marksheets for exam {exam_id}")
        return 0

    assigned_count = 0
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
        assigned_count += 1

    logger.info(f"Auto-assigned {assigned_count} papers to {len(set(checker_ids))} checkers for exam {exam.title}")
    return assigned_count


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
