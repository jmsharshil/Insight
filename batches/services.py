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
    Finds or creates an appropriate Batch for `student` and creates a BatchStudent.
    Also updates Student.batch FK and creates a BatchHistory entry.

    Fixed: 
    - Resolve course_obj FIRST (consistent lookup for find/create; fixes cases where 
      course__levels__course_type filter failed due to missing CourseLevels).
    - Annotate enrolled_count to avoid N+1 queries.
    - Safe organization lookup (prevents AttributeError if no .organization on Student).
    - Logging for debugging batch decisions.
    - Removed duplicate timezone imports.
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

    # Resolve course first (used for both lookup and creation). This was the main
    # source of the bug — existing_batches filter often returned empty.
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

    group_module = admission.group_module or ''

    # ── Step 1: find an existing batch with room (now uses exact course_obj) ──
    existing_batches = (
        Batch.objects
        .filter(
            course=course_obj,
            batch_attempt=batch_attempt,
            attempt_year=attempt_year,
            group_module=group_module,
            is_active=True,
        )
        .distinct()
        .annotate(enrolled_count=Count('batch_students'))
        .order_by('created_at')
    )

    batch = None
    for candidate in existing_batches:
        if candidate.enrolled_count < candidate.max_students:
            batch = candidate
            logger.info(
                f"Auto-assigning student {student.admission_number} to existing batch "
                f"{batch.name} (enrolled: {candidate.enrolled_count}/{batch.max_students})"
            )
            break

    # ── Step 2: create a new batch if none available ──────────────────────────
    if batch is None:
        # Atomically increment the sequence counter
        counter, _ = BatchSequenceCounter.objects.select_for_update().get_or_create(
            course_type=course_type,
            batch_attempt=batch_attempt,
            attempt_year=attempt_year,
            defaults={'last_sequence': 100},
        )
        counter.last_sequence += 1
        counter.save(update_fields=['last_sequence'])

        sequence = counter.last_sequence
        year_suffix = str(attempt_year)[-2:]
        batch_name = f"{course_type}_{batch_attempt}_{year_suffix}_{sequence}".upper()

        today = timezone.now().date()

        # Safe organization resolution (Student may not have direct .organization attr)
        organization = None
        if getattr(student, 'branch', None) and getattr(student.branch, 'organization', None):
            organization = student.branch.organization
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
            branch=getattr(student, 'branch', None),
        )
        logger.info(
            f"Created new auto-batch {batch.name} for student {student.admission_number} "
            f"(course_type={course_type}, attempt={batch_attempt}-{attempt_year})"
        )

    # ── Step 3: enrol student ─────────────────────────────────────────────────
    batch_student, created = BatchStudent.objects.get_or_create(
        batch=batch,
        student=student,
    )
    if not created:
        logger.warning(f"Student {student.admission_number} was already enrolled in batch {batch.name}")

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
