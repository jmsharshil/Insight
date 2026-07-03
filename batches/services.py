"""
batches/services.py
Auto batch creation and assignment logic (E1).
"""
import logging
from django.db import transaction
from django.db.models import Count
from django.core.exceptions import ValidationError

logger = logging.getLogger(__name__)


@transaction.atomic
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

    attempt_year = admission.attempt_year
    if not attempt_year:
        attempt_year = timezone.now().year
        admission.attempt_year = attempt_year
        admission.save(update_fields=['attempt_year'])

    batch_attempt = admission.batch_attempt
    if not batch_attempt:
        batch_attempt = 'june'
        admission.batch_attempt = batch_attempt
        admission.save(update_fields=['batch_attempt'])

    course_type = admission.course or 'cseet'

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

    group_module = admission.group_module or ''

    # ── Step 1: find an existing batch with room (branch-scoped) ───────────────
    batch_qs = Batch.objects.filter(
        course=course_obj,
        batch_attempt=batch_attempt,
        attempt_year=attempt_year,
        group_module=group_module,
        is_active=True,
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

        today = timezone.now().date()

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
            # Placeholder dates — admin can update after creation
            start_date=today,
            end_date=today,
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