"""
batches/services.py
Auto batch creation and assignment logic (E1).
"""
import logging
from django.db import transaction
from django.core.exceptions import ValidationError

logger = logging.getLogger(__name__)


@transaction.atomic
def auto_assign_batch(student):
    """
    Finds or creates an appropriate Batch for `student` and creates a BatchStudent.
    Also updates Student.batch FK and creates a BatchHistory entry.

    Returns the created BatchStudent instance.
    Raises ValueError if admission is misconfigured.
    """
    from batches.models import (
        Batch, BatchStudent, BatchSequenceCounter, Course,
    )
    from students.models import BatchHistory

    admission = student.admission

    from django.utils import timezone

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

    # ── Step 1: find an existing batch with room ──────────────────────────────
    # Course has no course_type; filter via CourseLevel which does.
    existing_batches = (
        Batch.objects
        .filter(
            course__levels__course_type=course_type,
            batch_attempt=batch_attempt,
            attempt_year=attempt_year,
            is_active=True,
        )
        .distinct()
        .order_by('created_at')
    )

    batch = None
    for candidate in existing_batches:
        enrolled_count = candidate.batch_students.count()
        if enrolled_count < candidate.max_students:
            batch = candidate
            break

    # ── Step 2: create a new batch if none available ──────────────────────────
    if batch is None:
        # Resolve Course via CourseLevel.course_type, then fall back to name match
        course_obj = (
            Course.objects.filter(levels__course_type=course_type, is_active=True).first()
            or Course.objects.filter(name__icontains=course_type, is_active=True).first()
            or Course.objects.filter(is_active=True).first()
        )
        if course_obj is None:
            raise ValueError(
                f"No active Course found for course_type='{course_type}'. "
                "Please create a Course with a matching CourseLevel before enrolling students."
            )

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
        # e.g. cseet_oct_26_101
        year_suffix = str(attempt_year)[-2:]
        batch_name = f"{course_type}_{batch_attempt}_{year_suffix}_{sequence}"

        from django.utils import timezone
        today = timezone.now().date()
        batch = Batch.objects.create(
            course=course_obj,
            name=batch_name,
            batch_attempt=batch_attempt,
            attempt_year=attempt_year,
            auto_sequence=sequence,
            is_auto_created=True,
            is_active=True,
            # Placeholder dates — admin can update after creation
            start_date=today,
            end_date=today,
        )

    # ── Step 3: enrol student ─────────────────────────────────────────────────
    batch_student, _ = BatchStudent.objects.get_or_create(
        batch=batch,
        student=student,
    )

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
