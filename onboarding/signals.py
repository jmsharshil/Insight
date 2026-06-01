"""
onboarding/signals.py — Cross-module signals for Admissions → Student pipeline.

Fires when an Admission's status changes to 'enrolled', triggering
automatic Student profile and User account creation.
"""

import logging
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(post_save, sender='onboarding.Admission')
def admission_status_changed(sender, instance, created, **kwargs):
    """
    When an Admission is marked as 'enrolled', auto-create:
      1. A User account (role=student) if one doesn't exist
      2. A Student profile linked to the admission

    This extracts the inline logic from onboarding/views.py.
    """
    if created:
        return  # Only trigger on updates

    if instance.status != 'enrolled':
        return

    try:
        from students.models import Student

        # Avoid duplicate student
        if Student.objects.filter(admission=instance).exists():
            logger.info(f"Student already exists for Admission {instance.id}")
            return

        # Create user account for the student
        from django.contrib.auth import get_user_model
        User = get_user_model()

        email = instance.student_email or instance.lead.email if instance.lead else ''
        phone = instance.student_phone or instance.lead.phone if instance.lead else ''
        name = instance.student_name or ''

        # Generate unique username
        base_username = email.split('@')[0] if email else f"student_{instance.id.hex[:8]}"
        username = base_username
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f"{base_username}_{counter}"
            counter += 1

        user = User.objects.create_user(
            username=username,
            email=email,
            password=None,  # Will be set via OTP/reset flow
            role='student',
            name=name,
            phone=phone,
            branch=instance.branch,
        )
        user.is_active = True
        user.save(update_fields=['is_active'])

        # Create student profile
        name_parts = name.split(' ', 1)
        student = Student.objects.create(
            admission=instance,
            user=user,
            branch=instance.branch,
            first_name=name_parts[0] if name_parts else '',
            surname=name_parts[1] if len(name_parts) > 1 else '',
            father_name=getattr(instance, 'father_name', ''),
            mother_name=getattr(instance, 'mother_name', ''),
            dob=getattr(instance, 'dob', None) or '2000-01-01',
            email=email,
            phone_student=phone,
            phone_father=getattr(instance, 'father_phone', '') or phone,
            street=getattr(instance, 'address', '') or '',
            city=getattr(instance, 'city', '') or '',
            state=getattr(instance, 'state', '') or '',
            pincode=getattr(instance, 'pincode', '') or '',
            course=instance.course or '',
            group_module=getattr(instance, 'group_module', '') or '',
            batch_attempt=getattr(instance, 'batch_attempt', '') or '',
            qualification=getattr(instance, 'qualification', '') or '',
            location=getattr(instance, 'location', '') or '',
            category=getattr(instance, 'category', '') or '',
        )

        logger.info(
            f"Auto-created Student {student.admission_number} "
            f"(user={user.username}) from Admission {instance.id}"
        )

    except Exception as e:
        logger.error(f"Failed to create Student from Admission {instance.id}: {e}", exc_info=True)
