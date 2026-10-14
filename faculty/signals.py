from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import FacultyProfile


@receiver(post_save, sender=FacultyProfile)
def sync_faculty_profile_to_user(sender, instance, **kwargs):
    """Keep duplicated faculty fields synced from FacultyProfile to User."""
    user = getattr(instance, 'user', None)
    if not user:
        return

    fields_to_sync = [
        'qualification', 'specialization', 'subject_expertise',
        'level', 'employment_type', 'joining_date', 'hourly_rate',
        'session_hours', 'salary', 'salary_retention_percentage',
        'bank_account', 'ifsc_code', 'pan_number',
        'work_start_time', 'work_end_time',
    ]

    updated_fields = []
    for field in fields_to_sync:
        profile_value = getattr(instance, field, None)
        if getattr(user, field, None) != profile_value:
            setattr(user, field, profile_value)
            updated_fields.append(field)

    if 'work_start_time' in updated_fields or 'work_end_time' in updated_fields:
        if user.work_start_time and user.work_end_time:
            from auth_user.utils import calculate_working_hours
            user.working_hours = calculate_working_hours(user.work_start_time, user.work_end_time)
            if 'working_hours' not in updated_fields:
                updated_fields.append('working_hours')

    if updated_fields:
        user.save(update_fields=updated_fields)
