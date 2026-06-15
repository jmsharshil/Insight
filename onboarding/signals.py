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
        from students.models import Student, ParentLink

        # Avoid duplicate student
        if Student.objects.filter(admission=instance).exists():
            logger.info(f"Student already exists for Admission {instance.id}")
            return

        # Create user account for the student
        from django.contrib.auth import get_user_model
        User = get_user_model()

        email = instance.email or (instance.lead.email if instance.lead else '')
        phone = instance.phone_student or (instance.lead.phone_student if instance.lead else '')
        name = ' '.join(filter(None, [instance.first_name, instance.surname]))

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
            assigned_counsellor=instance.assigned_counsellor,
            first_name=name_parts[0] if name_parts else '',
            surname=name_parts[1] if len(name_parts) > 1 else '',
            father_name=getattr(instance, 'father_name', ''),
            mother_name=getattr(instance, 'mother_name', ''),
            dob=instance.dob or '2000-01-01',
            email=email,
            email_parent=instance.email_parent or '',
            phone_student=phone,
            phone_student_2=instance.phone_student_2 or '',
            phone_father=instance.phone_father or (instance.lead.phone_father if instance.lead else ''),
            phone_father_2=instance.phone_father_2 or '',
            street=instance.street or '',
            apartment=instance.apartment or '',
            city=instance.city or '',
            state=instance.state or '',
            pincode=instance.pincode or '',
            country=instance.country or 'India',
            course=instance.course or '',
            group_module=instance.group_module or '',
            batch_attempt=instance.batch_attempt or '',
            qualification=instance.qualification or '',
            location=instance.location or '',
            category=instance.category or '',
            notes=instance.note or '',
            photo=instance.doc_photo if getattr(instance, 'doc_photo', None) else None,
            doc_signature=instance.doc_signature if getattr(instance, 'doc_signature', None) else None,
            doc_dob_certificate=instance.doc_dob_certificate if getattr(instance, 'doc_dob_certificate', None) else None,
            doc_id_proof=instance.doc_id_card if getattr(instance, 'doc_id_card', None) else None,
            doc_tenth_marksheet=instance.doc_tenth_marksheet if getattr(instance, 'doc_tenth_marksheet', None) else None,
            doc_twelfth_marksheet=instance.doc_twelfth_marksheet if getattr(instance, 'doc_twelfth_marksheet', None) else None,
            doc_category_cert=instance.doc_category_cert if getattr(instance, 'doc_category_cert', None) else None,
            doc_graduation_cert=instance.doc_graduation_cert if getattr(instance, 'doc_graduation_cert', None) else None,
        )

        parent_users = list(user.linked_parents.all())
        if not parent_users and instance.email_parent:
            from auth_user.models import User as AuthUser
            parent_user = AuthUser.objects.filter(
                email__iexact=instance.email_parent,
                role='parents',
            ).first()
            if parent_user:
                parent_users.append(parent_user)

        for parent_user in parent_users:
            ParentLink.objects.get_or_create(
                student=student,
                parent=parent_user,
                defaults={
                    'relationship': 'father',
                    'is_primary': True,
                }
            )

        logger.info(
            f"Auto-created Student {student.admission_number} "
            f"(user={user.username}) from Admission {instance.id}"
        )

    except Exception as e:
        logger.error(f"Failed to create Student from Admission {instance.id}: {e}", exc_info=True)
