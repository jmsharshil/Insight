"""
fees/services.py
Fee auto-creation logic (E1).
"""
import logging
from django.core.exceptions import ValidationError

logger = logging.getLogger(__name__)


def create_student_fee(student):
    """
    Creates a StudentFee for `student` using the fee_structure set on the
    linked Admission (or falls back to the latest active FeeStructure for
    the student's course).

    Returns the StudentFee instance.
    Raises django.core.exceptions.ValidationError if no FeeStructure found.
    """
    from fees.models import FeeStructure, StudentFee

    admission = student.admission

    # 1. Prefer fee_structure pinned on the admission
    fs = admission.fee_structure

    # 2. Fallback: latest active FeeStructure for the course type
    if fs is None:
        from django.db import models
        fs = (
            FeeStructure.objects
            .filter(
                models.Q(level__course_type=admission.course) | 
                models.Q(course__levels__course_type=admission.course),
                is_active=True,
            )
            .order_by('-created_at')
            .first()
        )

    if fs is None:
        raise ValidationError(
            f"No active FeeStructure found for course '{admission.course}'. "
            "Please create one before enrolling students."
        )

    # 3. get_or_create to avoid duplicates
    student_fee, created = StudentFee.objects.get_or_create(
        student=student,
        fee_structure=fs,
        defaults={
            'total_amount': fs.total_amount,
            'status': 'approval_pending',
        },
    )

    # 4. Sync admission payment if present
    payment_amount = getattr(admission, 'payment_amount', 0) or 0
    if admission.payment_screenshot or admission.transaction_id or payment_amount:
        from fees.models import Payment
        from django.utils import timezone
        
        Payment.objects.get_or_create(
            student=student,
            student_fee=student_fee,
            transaction_ref=admission.transaction_id or '',
            defaults={
                'amount': payment_amount,
                'payment_mode': 'online',
                'payment_proof': admission.payment_screenshot,
                'status': 'verified',
                'payment_date': timezone.now().date(),
                'note': f"Auto-created from admission {admission.id}. Transaction ID: {admission.transaction_id or 'N/A'}"
            }
        )

    return student_fee
