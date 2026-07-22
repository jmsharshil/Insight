"""
Django signals for leave module.

Automatically creates / updates LeaveBalance records for every eligible staff
member whenever a LeavePolicy is saved (created or updated).
"""

import logging
from decimal import Decimal

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

logger = logging.getLogger(__name__)


@receiver(post_save, sender='leave.LeavePolicy')
def sync_leave_balances_on_policy_save(sender, instance, created, **kwargs):
    """
    Fired after every LeavePolicy save.
    Creates a LeaveBalance for each eligible staff member in the policy's
    branch (or updates total_days if the balance already exists).
    """
    policy = instance

    # Skip inactive policies
    if not policy.is_active:
        return

    branch = policy.branch
    year = timezone.now().year

    from django.contrib.auth import get_user_model
    from .models import LeaveBalance

    User = get_user_model()

    STAFF_ROLES = [
        'super_admin', 'faculty', 'branch_manager',
        'admin_senior_executive', 'admin_executive',
        'front_desk', 'counsellor', 'sales_senior_executive',
        'sales_executive', 'tele_caller', 'exam_supervisor',
        'paper_checker', 'accountant',
    ]

    # ── Collect eligible users ──────────────────────────────────────────
    #  1. Users whose User.branch == this branch
    #  2. Faculty whose FacultyProfile.branch == this branch
    #  3. super_admin users (org-wide, always eligible)
    eligible_user_ids = set()

    # Direct branch FK on User model
    branch_users = User.objects.filter(
        role__in=STAFF_ROLES,
        is_active=True,
        branch=branch,
    ).values_list('id', flat=True)
    eligible_user_ids.update(branch_users)

    # FacultyProfile branch (some faculty have branch only on profile)
    try:
        from faculty.models import FacultyProfile
        faculty_user_ids = FacultyProfile.objects.filter(
            branch=branch,
            is_active=True,
            user__is_active=True,
            user__role__in=STAFF_ROLES,
        ).values_list('user_id', flat=True)
        eligible_user_ids.update(faculty_user_ids)
    except Exception:
        pass

    # Super admins — always get balances (scoped to org if available)
    sa_qs = User.objects.filter(role='super_admin', is_active=True)
    if branch.organization_id:
        sa_qs = sa_qs.filter(organization_id=branch.organization_id)
    eligible_user_ids.update(sa_qs.values_list('id', flat=True))

    # ── Create or update balances ───────────────────────────────────────
    created_count = 0
    updated_count = 0

    for uid in eligible_user_ids:
        carried = Decimal(0)
        if policy.carry_forward:
            prev = LeaveBalance.objects.filter(
                user_id=uid, leave_type=policy.leave_type, year=year - 1
            ).first()
            if prev:
                remaining = prev.remaining_days
                carried = min(remaining, Decimal(policy.max_carry_days))
                carried = max(carried, Decimal(0))

        balance, was_created = LeaveBalance.objects.get_or_create(
            user_id=uid,
            leave_type=policy.leave_type,
            year=year,
            defaults={
                'total_days': Decimal(policy.annual_quota),
                'carried_forward': carried,
            },
        )
        if was_created:
            created_count += 1
        else:
            # Sync total_days with updated policy quota
            if balance.total_days != Decimal(policy.annual_quota):
                balance.total_days = Decimal(policy.annual_quota)
                balance.save(update_fields=['total_days'])
                updated_count += 1

    logger.info(
        f"[LEAVE SIGNAL] Policy '{policy.leave_type}' saved for branch={branch.id}. "
        f"Balances created={created_count}, updated={updated_count}, "
        f"eligible_users={len(eligible_user_ids)}, year={year}"
    )
