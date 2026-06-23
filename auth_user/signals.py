from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender='auth_user.User')
def sync_retention_to_faculty_profile(sender, instance, **kwargs):
    """
    When a User's salary_retention_percentage is updated,
    automatically sync it to their linked FacultyProfile.
    """
    try:
        fp = instance.faculty_profile
        if fp.salary_retention_percentage != instance.salary_retention_percentage:
            fp.salary_retention_percentage = instance.salary_retention_percentage
            fp.save(update_fields=['salary_retention_percentage'])
    except Exception:
        # User may not have a faculty profile (e.g., student, staff)
        pass
