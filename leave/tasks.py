import logging
from decimal import Decimal
from django.utils import timezone
from .models import LeaveBalance
from django.contrib.auth import get_user_model

logger = logging.getLogger(__name__)

def accrue_monthly_leaves_task():
    """
    Runs daily via the scheduler. On the 1st of every month,
    adds 1.5 days to 'casual' leave balance for all active staff.
    
    Leave cycle: April 1 → March 31 (financial year).
    - Existing employees: cycle always starts April 1.
    - New employees: cycle starts from their joining month and runs to March 31.
    Only accrues for months on/after the user's joining date.
    """
    today = timezone.now().date()

    # Only run this on the 1st day of the month
    if today.day != 1:
        return

    User = get_user_model()

    staff_roles = [
        'faculty', 'branch_manager', 'admin_senior_executive', 'admin_executive',
        'front_desk', 'counsellor', 'sales_senior_executive', 'sales_executive',
        'tele_caller', 'exam_supervisor', 'paper_checker', 'accountant',
        'house_keeping', 'security',
    ]

    staff_members = User.objects.filter(role__in=staff_roles, is_active=True)
    leave_type_to_accrue = 'casual'

    accrued_amount = Decimal('1.5')
    updated_count = 0

    # Determine financial year: April 2024 → March 2025 is FY 2024
    if today.month < 4:
        financial_year = today.year - 1
    else:
        financial_year = today.year

    for user in staff_members:
        # Get joining date: prefer faculty_profile, else fall back to user.created_at date
        joining_date = None
        try:
            joining_date = user.faculty_profile.joining_date
        except Exception:
            pass
        if joining_date is None:
            joining_date = user.created_at.date() if hasattr(user, 'created_at') else None

        # Only accrue for users whose joining date is on or before today
        if joining_date and joining_date > today:
            continue

        # Skip if the user joined after this month started (wait until next accrual)
        if joining_date and (joining_date.year, joining_date.month) > (today.year, today.month):
            continue

        # Get or create balance for current financial year
        balance, created = LeaveBalance.objects.get_or_create(
            user=user,
            leave_type=leave_type_to_accrue,
            year=financial_year,
            defaults={
                'total_days': accrued_amount,
                'used_days': Decimal(0),
                'carried_forward': Decimal(0)
            }
        )

        # If the balance already existed, add 1.5 to it
        if not created:
            balance.total_days += accrued_amount
            balance.save(update_fields=['total_days'])

        updated_count += 1

    logger.info(f"[LEAVE ACCRUAL] Accrued {accrued_amount} days of {leave_type_to_accrue} leave for {updated_count} users (FY {financial_year}).")


