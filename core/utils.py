"""
core/utils.py — Shared helper functions used across all apps.

Centralises the repeated _user_role / _user_branch_id helpers that were
previously copy-pasted in attendance, exams, leave, and payroll views.
"""

import logging

logger = logging.getLogger(__name__)


def get_user_role(user):
    """Return the role string of the authenticated user."""
    return getattr(user, 'role', None)


def get_user_branch_id(user):
    """
    Resolve the branch_id for the given user.

    Priority:
      1. user.branch_id   (User model FK)
      2. user.faculty_profile.branch_id  (FacultyProfile)
    """
    # Direct FK on User model
    branch_id = getattr(user, 'branch_id', None)
    if branch_id:
        return branch_id

    # Fallback: FacultyProfile
    try:
        from faculty.models import FacultyProfile
        fp = FacultyProfile.objects.only('branch_id').get(user=user)
        return fp.branch_id
    except Exception:
        pass

    return None


def get_student_profile(user):
    """
    Return the Student/StudentProfile for a user with role='student'.
    Returns None if not found.
    """
    try:
        from students.models import Student
        return Student.objects.select_related('branch', 'batch').get(user=user)
    except Exception:
        return None
