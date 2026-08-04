"""
batches/services.py
Auto batch creation and assignment logic (E1).
"""
import logging
from datetime import date
from django.db import transaction
from django.db.models import Count
from django.core.exceptions import ValidationError

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# ICSI Exam Registration Deadline Rules
# ═══════════════════════════════════════════════════════════════════════════════
#
# CSEET (3 sessions/year — 4-month gap before exam):
#   June exam      → last registration: 31 January  (same year)
#   October exam   → last registration: 31 May       (same year)
#   February exam  → last registration: 31 October   (PREVIOUS year)
#
# CS Executive / Professional (2 sessions/year):
#   June exam  - Both Modules  → last registration: 30 November (previous year) [6 months]
#   June exam  - Single Module → last registration: 31 January  (same year)     [4 months]
#   Dec  exam  - Both Modules  → last registration: 31 May      (same year)     [6 months]
#   Dec  exam  - Single Module → last registration: 31 July     (same year)     [4 months]
#
# "Single Module" covers module_1 / module_2 / module_3.
# "Both Modules"  covers 'both' / 'full'.
# ═══════════════════════════════════════════════════════════════════════════════

def get_exam_attempt_year(course: str, batch_attempt: str, group_module: str, form_date: date) -> int:
    """
    Return the exam attempt year a student is targeting, based on the
    admission form-fill date and ICSI registration deadline rules.

    Logic:
      1. For each candidate upcoming exam session (current year, next year),
         compute the registration deadline.
      2. Return the year of the FIRST session whose deadline is still in the
         future (i.e. form_date <= deadline).
      3. If all deadlines for the current year have passed, return next year.

    Args:
        course       : 'cseet' | 'cs_executive' | 'cs_professional'
        batch_attempt: 'june' | 'oct' | 'feb' | 'dec'
        group_module : 'both' | 'full' | 'module_1' | 'module_2' | 'module_3'
        form_date    : date the admission form was submitted/filled

    Returns:
        int — the 4-digit exam year the student can realistically target
    """
    is_both = group_module in ('both', 'full')
    y = form_date.year  # start candidate search from current year

    def _deadline(attempt: str, year: int) -> date:
        """Return the registration deadline for the given attempt and year."""
        if course == 'cseet':
            # CSEET deadlines are the same regardless of module
            if attempt == 'june':
                return date(year, 1, 31)      # 31 Jan (same year)
            elif attempt == 'oct':
                return date(year, 5, 31)      # 31 May (same year)
            elif attempt == 'feb':
                return date(year - 1, 10, 31) # 31 Oct of PREVIOUS year
        else:
            # CS Executive / Professional
            if attempt == 'june':
                if is_both:
                    return date(year - 1, 11, 30)  # 30 Nov previous year
                else:
                    return date(year, 1, 31)        # 31 Jan same year
            elif attempt == 'dec':
                if is_both:
                    return date(year, 5, 31)        # 31 May same year
                else:
                    return date(year, 7, 31)        # 31 Jul same year
        # Fallback — shouldn't reach here with valid data
        return date(year, 1, 31)

    # Check up to 3 upcoming years to handle edge cases
    for candidate_year in [y, y + 1, y + 2]:
        deadline = _deadline(batch_attempt, candidate_year)
        if form_date <= deadline:
            logger.info(
                f"[BatchYear] course={course} attempt={batch_attempt} "
                f"module={group_module} form_date={form_date} → "
                f"exam_year={candidate_year} (deadline={deadline})"
            )
            return candidate_year

    # Ultimate fallback: return year after next
    return y + 2


def get_batch_dates(course: str, batch_attempt: str, group_module: str, attempt_year: int):
    """
    Compute the coaching batch start_date and end_date based on the ICSI
    exam schedule for the given course / attempt / module / year.

    Coaching period = day after registration deadline  →  last day before exam.

    CSEET (registration deadline → coaching starts):
      June   (year Y): coaching Feb 1  – May 31  (exam in June)
      October(year Y): coaching Jun 1  – Sep 30  (exam in Oct)
      February(year Y): coaching Nov 1 (Y-1) – Jan 31 Y (exam in Feb)

    CS Executive / Professional:
      June  – Both   (year Y): coaching Dec 1 (Y-1) – May 31 Y
      June  – Single (year Y): coaching Feb 1 Y     – May 31 Y
      Dec   – Both   (year Y): coaching Jun 1 Y     – Nov 30 Y
      Dec   – Single (year Y): coaching Aug 1 Y     – Nov 30 Y

    Returns:
        (start_date: date, end_date: date)
    """
    from calendar import monthrange

    def _last_day(y: int, m: int) -> date:
        return date(y, m, monthrange(y, m)[1])

    is_both = group_module in ('both', 'full')
    y = attempt_year

    if course == 'cseet':
        if batch_attempt == 'june':
            return date(y, 2, 1), _last_day(y, 5)      # Feb 1 – May 31
        elif batch_attempt == 'oct':
            return date(y, 6, 1), _last_day(y, 9)      # Jun 1 – Sep 30
        elif batch_attempt == 'feb':
            return date(y - 1, 11, 1), _last_day(y, 1) # Nov 1 (prev) – Jan 31
    else:
        # CS Executive / Professional
        if batch_attempt == 'june':
            if is_both:
                return date(y - 1, 12, 1), _last_day(y, 5) # Dec 1 (prev) – May 31
            else:
                return date(y, 2, 1), _last_day(y, 5)       # Feb 1 – May 31
        elif batch_attempt == 'dec':
            if is_both:
                return date(y, 6, 1), _last_day(y, 11)      # Jun 1 – Nov 30
            else:
                return date(y, 8, 1), _last_day(y, 11)      # Aug 1 – Nov 30

    # Generic fallback — Jan 1 to Dec 31 of attempt year
    return date(y, 1, 1), date(y, 12, 31)

def auto_assign_batch(student):
    """
    Finds or creates an appropriate Batch for `student` (now fully branch-aware).
    This fixes the issue where batches were not created separately per branch
    for each level/course_type, and names were not differentiated.

    Changes:
    - Branch resolved from student or admission and used in all queries/counters.
    - existing_batches now filtered by branch (prevents cross-branch reuse).
    - BatchSequenceCounter now scoped per branch.
    - Batch name includes branch prefix (e.g. "B1 CSEET JUNE'25 101") for clear differentiation.
    - Model.save() batch_code also now uses per-branch sequencing.
    """
    from batches.models import (
        Batch, BatchStudent, BatchSequenceCounter, Course,
    )
    from students.models import BatchHistory
    from django.utils import timezone

    admission = student.admission

    # ── Resolve batch_attempt first (needed for year calculation) ─────────────
    batch_attempt = admission.batch_attempt
    if not batch_attempt:
        batch_attempt = 'june'
        admission.batch_attempt = batch_attempt
        admission.save(update_fields=['batch_attempt'])

    course_type = admission.course or 'cseet'
    group_module = admission.group_module or ''

    # ── Smart attempt_year via ICSI registration deadline rules ───────────────
    attempt_year = admission.attempt_year
    if not attempt_year:
        # Use the admission form submission date (submitted_at) as the reference.
        # Fall back to today if for some reason it's missing.
        form_date = (
            admission.submitted_at.date()
            if getattr(admission, 'submitted_at', None)
            else timezone.now().date()
        )
        attempt_year = get_exam_attempt_year(
            course=course_type,
            batch_attempt=batch_attempt,
            group_module=group_module,
            form_date=form_date,
        )
        admission.attempt_year = attempt_year
        admission.save(update_fields=['attempt_year'])

    # Resolve course first (used for both lookup and creation).
    course_obj = (
        Course.objects.filter(levels__course_type=course_type, is_active=True).first()
        or Course.objects.filter(name__icontains=course_type, is_active=True).first()
        or Course.objects.filter(is_active=True).first()
    )
    if course_obj is None:
        raise ValueError(
            f"No active Course found for course_type='{course_type}'. "
            "Please create a Course (with matching CourseLevel) before enrolling students."
        )

    # ── Branch resolution (core fix for per-branch batch creation) ─────────────
    branch = None
    if getattr(student, 'branch', None):
        branch = student.branch
    elif getattr(student, 'admission', None) and getattr(student.admission, 'branch', None):
        branch = student.admission.branch

    today = timezone.now().date()

    # ── Step 1: find an existing, non-expired batch with room (branch-scoped) ───
    batch_qs = Batch.objects.filter(
        course=course_obj,
        batch_attempt=batch_attempt,
        attempt_year=attempt_year,
        group_module=group_module,
        is_active=True,
        end_date__gte=today,      # ← never reuse a batch whose coaching period ended
    )
    if branch:
        batch_qs = batch_qs.filter(branch=branch)
    else:
        batch_qs = batch_qs.filter(branch__isnull=True)

    existing_batches = (
        batch_qs
        .distinct()
        .annotate(enrolled_count=Count('batch_students'))
        .order_by('created_at')
    )

    batch = None
    for candidate in existing_batches:
        if candidate.enrolled_count < candidate.max_students:
            batch = candidate
            logger.info(
                f"Auto-assigning student {getattr(student, 'admission_number', student.id)} to existing batch "
                f"{batch.name} (enrolled: {candidate.enrolled_count}/{batch.max_students})"
            )
            break

    # ── Step 2: create a new batch if none available (branch-aware naming) ─────
    if batch is None:
        # Atomically increment the sequence counter (now per-branch)
        counter_kwargs = {
            'course_type': course_type,
            'batch_attempt': batch_attempt,
            'attempt_year': attempt_year,
        }
        if branch:
            counter_kwargs['branch'] = branch
        counter, _ = BatchSequenceCounter.objects.select_for_update().get_or_create(
            **counter_kwargs,
            defaults={'last_sequence': 100},
        )
        counter.last_sequence += 1
        counter.save(update_fields=['last_sequence'])

        sequence = counter.last_sequence
        year_suffix = str(attempt_year)[-2:]

        # Compute branch prefix for name differentiation (matches updated Batch.save())
        branch_prefix = ''
        if branch and getattr(branch, 'name', None):
            # Try to extract a numeric suffix from branch name (e.g. "BRN-2025-0001" -> "B1")
            try:
                parts = branch.name.split('-')
                if len(parts) >= 2:
                    bseq = parts[-1]  # last segment
                    branch_prefix = f"{bseq.lstrip('0') or '0'}"
                else:
                    # Fallback: use first 4 chars of branch name
                    branch_prefix = f"{branch.name[:4]}"
            except Exception:
                branch_prefix = 'BXX'

        if branch_prefix:
            batch_name = f"{branch_prefix}_{course_type.upper()}_{batch_attempt.upper()}_{year_suffix}_{sequence}"
        else:
            batch_name = f"{course_type.upper()}_{batch_attempt.upper()}_{year_suffix}_{sequence}"

        # Compute ICSI-aligned coaching dates for this batch
        batch_start, batch_end = get_batch_dates(
            course=course_type,
            batch_attempt=batch_attempt,
            group_module=group_module,
            attempt_year=attempt_year,
        )
        # If the computed start is in the past, use today so the batch is
        # immediately active (student is joining mid-session).
        if batch_start < today:
            batch_start = today

        # Safe organization resolution
        organization = None
        if branch and getattr(branch, 'organization', None):
            organization = branch.organization
        elif getattr(student.admission, 'branch', None) and getattr(student.admission.branch, 'organization', None):
            organization = student.admission.branch.organization

        batch = Batch.objects.create(
            course=course_obj,
            name=batch_name,
            batch_attempt=batch_attempt,
            attempt_year=attempt_year,
            group_module=group_module,
            auto_sequence=sequence,
            is_auto_created=True,
            is_active=True,
            start_date=batch_start,
            end_date=batch_end,
            organization=organization,
            branch=branch,
        )
        logger.info(
            f"Created new auto-batch {batch.name} (branch={getattr(branch, 'name', 'None')}) "
            f"for student {getattr(student, 'admission_number', student.id)} "
            f"(course_type={course_type}, attempt={batch_attempt}-{attempt_year})"
        )

    # ── Step 3: enrol student ─────────────────────────────────────────────────
    batch_student, created = BatchStudent.objects.get_or_create(
        batch=batch,
        student=student,
    )
    if not created:
        logger.warning(f"Student {getattr(student, 'admission_number', student.id)} was already enrolled in batch {batch.name}")

    # ── Step 4: update Student.batch FK ──────────────────────────────────────
    from students.models import Student as StudentModel
    StudentModel.objects.filter(pk=student.pk).update(
        batch=batch, 
        current_batch_name=batch.name
    )
    student.batch = batch
    student.current_batch_name = batch.name

    # ── Step 5: log batch history ─────────────────────────────────────────────
    BatchHistory.objects.create(
        student=student,
        batch_name=batch.name,
        reason='Auto-assigned on enrollment',
    )

    return batch_student