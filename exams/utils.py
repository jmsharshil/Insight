import uuid
import math
import logging
from datetime import timedelta
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


# ── Stub notification helper ──────────────────────────────────────────────────

def notify(recipient_user_id, title, body, metadata=None, email_template=None, email_context=None, email_subject=None):
    from chat.notifications import send_system_notification
    if recipient_user_id:
        send_system_notification(
            user_id=str(recipient_user_id),
            title=title,
            body=body,
            metadata=metadata,
            email_template=email_template,
            email_context=email_context,
            email_subject=email_subject,
        )


def build_absolute_url(path, request=None):
    """Return a stable absolute URL for email links using configured backend settings."""
    if not path:
        return ''

    if path.startswith(('http://', 'https://')):
        return path

    base_url = getattr(settings, 'BASE_URL', '').strip() or getattr(settings, 'FRONTEND_BASE_URL', '').strip()
    if base_url:
        normalized_path = path if path.startswith('/') else f'/{path}'
        url = f"{base_url.rstrip('/')}{normalized_path}"
        return url.replace('localhost', '127.0.0.1')

    if request is not None:
        return request.build_absolute_uri(path)

    return path


def group_questions(serialized_questions):
    """
    Groups paragraph_mcq questions that share the same paragraph_text.
    Other questions remain standalone in the array.
    """
    grouped_data = []
    paragraph_groups = {}

    for q in serialized_questions:
        if q.get('question_type') == 'paragraph_mcq' and q.get('paragraph_text'):
            p_text = q['paragraph_text'].strip()
            if p_text not in paragraph_groups:
                group_obj = {
                    'paragraph_text': p_text,
                    'question_type': 'paragraph_mcq',
                    'questions': []
                }
                paragraph_groups[p_text] = group_obj
                grouped_data.append(group_obj)
            
            # Make a copy and remove paragraph_text to avoid redundancy
            q_copy = dict(q)
            q_copy.pop('paragraph_text', None)
            paragraph_groups[p_text]['questions'].append(q_copy)
        else:
            grouped_data.append(q)

    return grouped_data


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
        pr, created = PublishedResult.objects.update_or_create(
            exam=exam, student=session.student,
            defaults={'marks_obtained': marks, 'total_marks': exam.total_marks, 'percentage': pct, 'is_pass': passed},
        )
        if created:
            from results.utils import notify_parents_of_exam_result
            notify_parents_of_exam_result([pr])

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

    if not requires_paper_checking(exam, has_subjective_questions=has_subjective):
        auto_grade_mcq(session.id)
    else:
        # Create MarkSheet and assign paper checker immediately
        from results.models import MarkSheet
        MarkSheet.objects.get_or_create(
            exam=exam,
            student=session.student,
            defaults={'is_submitted': False}
        )
        assign_papers_to_checker(exam.id)

    return session


def requires_paper_checking(exam, has_subjective_questions=False):
    """Return True when an exam should be reviewed by paper checkers."""
    exam_mode = getattr(exam, 'exam_mode', None)
    exam_type = getattr(exam, 'exam_type', None)

    if exam_mode == 'online' and exam_type == 'mcq':
        return False
    return True


def get_available_paper_checkers(exam):
    """
    Returns list of paper_checker User IDs available for this exam.
    If no paper_checkers M2M set on Exam, falls back to ALL active paper_checkers
    in the same branch. Then filters by work time overlap (if configured on User).
    """
    from .models import Exam
    from django.contrib.auth import get_user_model
    User = get_user_model()

    if not isinstance(exam, Exam):
        exam = Exam.objects.select_related('faculty', 'created_by', 'branch')\
                          .prefetch_related('paper_checkers').get(id=exam)

    if not exam.paper_checkers.exists():
        logger.warning(f"No paper_checkers configured for exam {exam.id}. Using branch-wide fallback.")
        # Branch-scoped fallback to ensure Exam always gets paper_checkers (M2M)
        qs = User.objects.filter(role='paper_checker', is_active=True)
        from django.db.models import Q
        org_id = getattr(exam, 'organization_id', None)
        if not org_id and getattr(exam, 'branch', None):
            org_id = exam.branch.organization_id
            
        q_filter = Q()
        if exam.branch_id:
            q_filter |= Q(branch_id=exam.branch_id)
        elif getattr(exam, 'branch', None):
            q_filter |= Q(branch_id=exam.branch.id)
            
        if org_id:
            q_filter |= Q(organization_id=org_id, branch__isnull=True)
            
        if q_filter:
            qs = qs.filter(q_filter)
        fallback_ids = list(qs.values_list('id', flat=True)[:20])  # cap to prevent overload
        if fallback_ids:
            logger.info(f"Using {len(fallback_ids)} branch paper_checkers as fallback for exam {exam.id}")
            return fallback_ids

        logger.error(f"No paper checkers available (even with fallback) for exam {exam.id}")
        return []

    # Get all possible checkers for this exam (when explicitly configured)
    checkers = list(exam.paper_checkers.all())

    available = []
    exam_start = exam.start_time
    exam_end = exam.end_time

    for checker in checkers:
        if not getattr(checker, 'is_active', True):
            continue

        work_start = getattr(checker, 'work_start_time', None)
        work_end = getattr(checker, 'work_end_time', None)

        if not work_start or not work_end:
            available.append(checker.id)
            continue

        if (work_start <= exam_end and work_end >= exam_start):
            available.append(checker.id)
        else:
            logger.info(f"Checker {checker.id} unavailable for exam time slot "
                       f"({exam_start}-{exam_end} vs their {work_start}-{work_end})")

    logger.info(f"Available paper checkers for exam {exam.id}: {len(available)}/{len(checkers)}")
    return available


def ensure_paper_checkers_for_exam(exam_or_id):
    """
    Ensures Exam.paper_checkers M2M is populated with available checkers (or branch
    fallback). Called via Exam.ensure_paper_checkers() method (from model + post_save
    signal + views). Does NOT assign to MarkSheet.paper_checker FK (per requirement:
    delay until exam=completed + auto_mark_absent in tasks.py).
    Guarantees paper_checker users see the exam early via Q(paper_checkers=user).
    """
    from .models import Exam
    if not isinstance(exam_or_id, Exam):
        exam = Exam.objects.select_related('branch', 'faculty', 'created_by')\
                          .prefetch_related('paper_checkers').get(id=exam_or_id)
    else:
        exam = exam_or_id

    if exam.paper_checkers.exists():
        logger.debug(f"Exam {exam.id} already has {exam.paper_checkers.count()} paper checkers.")
        return list(exam.paper_checkers.values_list('id', flat=True))

    checker_ids = get_available_paper_checkers(exam)
    if checker_ids:
        exam.paper_checkers.add(*checker_ids)
        logger.info(f"Ensured {len(checker_ids)} paper checkers assigned to exam {exam.id} via M2M.")
        # Clear any cached relation to ensure fresh query next time
        if hasattr(exam, '_prefetched_objects_cache'):
            exam._prefetched_objects_cache.pop('paper_checkers', None)
    return checker_ids


def assign_papers_to_checker(exam_id, checker_ids=None):
    """
    Distribute unassigned MarkSheets (round-robin) to paper checkers from the
    Exam.paper_checkers M2M pool. Sends email + notification + generates token.
    Per user request: This is NOW ONLY called AFTER exam ends (in completion task)
    and after all MarkSheets exist (via auto_mark_absent_after_exam + student submits).
    The M2M population on Exam happens earlier via ensure_paper_checkers_for_exam().
    FRD §4.6.2: email + in-app notify.
    """
    from results.models import MarkSheet
    from .models import Exam
    from .emails import send_checker_assignment_email

    exam = Exam.objects.select_related('branch').get(id=exam_id)

    if not requires_paper_checking(exam):
        logger.info(f"Skipping paper checker assignment for exam {exam_id} ({exam.title}) because it does not require manual review.")
        return 0

    if not checker_ids:
        # Rely on M2M (populated at creation). Fallback only if somehow empty.
        if not exam.paper_checkers.exists():
            logger.warning(f"No paper_checkers on exam {exam_id} at assignment time. Falling back.")
            checker_ids = get_available_paper_checkers(exam)
            if checker_ids:
                exam.paper_checkers.add(*checker_ids)
        else:
            checker_ids = list(exam.paper_checkers.values_list('id', flat=True))

    if not checker_ids:
        logger.error(f"No available paper checkers for exam {exam_id}. "
                    "Please configure paper_checkers on Exam.")
        return 0

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
    """Haversine check. Returns (is_allowed, distance_meters).
    Safely handles missing geo coords on exam (prevents TypeError/float(None)
    that was causing 500→502 errors for misconfigured 'strat' exams).
    """
    if exam.geo_radius_meters == 0:
        return True, 0.0

    if exam.geo_lat is None or exam.geo_lon is None:
        logger.warning(
            f"Exam {getattr(exam, 'id', 'unknown')} has geo_radius_meters={exam.geo_radius_meters} "
            f"but missing geo_lat/lon. Treating as no geo restriction."
        )
        return True, 0.0

    try:
        R = 6371000
        lat1 = math.radians(float(exam.geo_lat))
        lat2 = math.radians(float(student_lat))
        dlat = math.radians(float(student_lat) - float(exam.geo_lat))
        dlon = math.radians(float(student_lon) - float(exam.geo_lon))
        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        distance = R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return distance <= exam.geo_radius_meters, round(distance, 2)
    except (TypeError, ValueError) as e:
        logger.error(f"Geo boundary calculation failed for exam {getattr(exam, 'id', 'unknown')}: {e}")
        return True, 0.0


def generate_checker_token(marksheet):
    """Create a CheckerToken valid for 72 hours."""
    from .models import CheckerToken
    token_str = str(uuid.uuid4())
    CheckerToken.objects.create(
        marksheet=marksheet, token=token_str,
        expires_at=timezone.now() + timedelta(hours=72),
    )
    return token_str
