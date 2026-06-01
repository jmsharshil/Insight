import logging
from decimal import Decimal
from datetime import timedelta
from django.utils import timezone

logger = logging.getLogger(__name__)


# ── Stub notification helper ──────────────────────────────────────────────────

def notify(recipient_user_id, title, body, metadata=None):
    """Stub: push/in-app notification. Replace with real implementation."""
    logger.info(f"NOTIFY [{recipient_user_id}] {title}: {body} | meta={metadata}")


def calculate_leave_days(from_date, to_date, is_half_day=False,
                         sandwich_rule=False, branch=None):
    """
    FRD §4.9.3 — Sandwich Leave Policy.
    - If is_half_day: return 0.5
    - If sandwich_rule=True:
        -> Count ALL days between from_date and to_date (including weekends)
        -> ALSO include public holidays from PublicHoliday table for this branch
    - If sandwich_rule=False:
        -> Count only working days (Mon-Fri, excluding public holidays)
    - Return: Decimal value (supports 0.5 increments)
    """
    if is_half_day:
        return Decimal('0.5')

    # Get public holiday dates for this branch in the date range
    public_holiday_dates = set()
    if branch:
        from .models import PublicHoliday
        holidays = PublicHoliday.objects.filter(
            branch=branch,
            date__gte=from_date,
            date__lte=to_date,
        ).values_list('date', flat=True)
        public_holiday_dates = set(holidays)

    days = Decimal(0)
    current = from_date
    while current <= to_date:
        weekday = current.weekday()
        if sandwich_rule:
            # Sandwich rule: count ALL days (weekdays, weekends, and public holidays)
            days += Decimal(1)
        else:
            # Normal: count only weekdays, exclude public holidays
            if weekday < 5 and current not in public_holiday_dates:
                days += Decimal(1)
        current += timedelta(days=1)
    return days


def check_leave_overlap(user, from_date, to_date, exclude_id=None):
    """Check if user has overlapping approved leave."""
    from .models import LeaveApplication
    qs = LeaveApplication.objects.filter(
        applied_by=user,
        status='approved',
        from_date__lte=to_date,
        to_date__gte=from_date,
    )
    if exclude_id:
        qs = qs.exclude(id=exclude_id)
    conflict = qs.first()
    return (conflict is not None, conflict)


def initialize_leave_balances_for_year(branch, year):
    """Initialize leave balances for all active staff in a branch for the given year."""
    from .models import LeavePolicy, LeaveBalance
    from django.contrib.auth import get_user_model
    User = get_user_model()

    staff_roles = [
        'faculty', 'branch_manager', 'admin_senior_executive', 'admin_executive',
        'front_desk', 'counsellor', 'sales_senior_executive', 'sales_executive',
        'tele_caller', 'exam_supervisor', 'paper_checker', 'accountant',
    ]
    staff = User.objects.filter(role__in=staff_roles, is_active=True)
    policies = LeavePolicy.objects.filter(branch=branch, is_active=True)

    created_count = 0
    for user in staff:
        for policy in policies:
            carried = Decimal(0)
            if policy.carry_forward:
                prev = LeaveBalance.objects.filter(
                    user=user, leave_type=policy.leave_type, year=year - 1
                ).first()
                if prev:
                    remaining = prev.remaining_days
                    carried = min(remaining, Decimal(policy.max_carry_days))
                    carried = max(carried, Decimal(0))

            _, was_created = LeaveBalance.objects.get_or_create(
                user=user, leave_type=policy.leave_type, year=year,
                defaults={
                    'total_days': Decimal(policy.annual_quota),
                    'carried_forward': carried,
                },
            )
            if was_created:
                created_count += 1

    logger.info(f"Initialized {created_count} leave balances for branch={branch.id}, year={year}")
    return created_count


def check_late_entry_threshold(user, month, year):
    """
    NEW (FRD §4.9.3): called after every LateEntryRecord is created.
    If monthly penalized late count >= threshold, auto-create half-day leave.
    """
    from .models import LateEntryRecord, LeaveApplication, LeaveBalance
    from payroll.models import LateEntryPolicy

    # 1. Count penalized late entries for this month
    count = LateEntryRecord.objects.filter(
        user=user,
        date__month=month,
        date__year=year,
        is_penalized=True,
    ).count()

    # 2. Get policy
    branch_id = getattr(user, 'branch_id', None)
    if not branch_id:
        if hasattr(user, 'faculty_profile'):
            branch_id = user.faculty_profile.branch_id
    if not branch_id:
        return

    policy = LateEntryPolicy.objects.filter(branch_id=branch_id, is_active=True).first()
    if not policy:
        return

    # 3. Check if auto_halfday_deduction is enabled
    if not policy.auto_halfday_deduction:
        return

    # 4. Check threshold
    if count < policy.late_entry_threshold:
        return

    # 5. Idempotent check: only one auto-deduction per user per month
    today = timezone.now().date()
    existing = LeaveApplication.objects.filter(
        applied_by=user,
        is_auto_generated=True,
        from_date__month=month,
        from_date__year=year,
    ).exists()
    if existing:
        return

    # 6. Auto-create half-day leave
    # Try casual first, fall back to unpaid if balance exhausted
    leave_type = 'casual'
    balance = LeaveBalance.objects.filter(
        user=user, leave_type='casual', year=year,
    ).first()
    if not balance or balance.remaining_days < Decimal('0.5'):
        leave_type = 'unpaid'

    leave = LeaveApplication.objects.create(
        applied_by=user,
        branch_id=branch_id,
        leave_type=leave_type,
        from_date=today,
        to_date=today,
        is_half_day=True,
        total_days=Decimal('0.5'),
        reason=f"Auto-deducted: {count} late entries in {month}/{year}",
        is_auto_generated=True,
        status='approved',
    )

    # Deduct balance
    if leave_type != 'unpaid' and balance:
        balance.used_days += Decimal('0.5')
        balance.save(update_fields=['used_days'])

    # Mark latest LateEntryRecord
    latest = LateEntryRecord.objects.filter(
        user=user,
        date__month=month,
        date__year=year,
        is_penalized=True,
    ).order_by('-date', '-created_at').first()
    if latest:
        latest.auto_deduction_triggered = True
        latest.save(update_fields=['auto_deduction_triggered'])

    # Notify user
    notify(
        str(user.id),
        title="Half-day auto-deducted",
        body=f"You have {count} late entries this month. 0.5 leave day auto-deducted.",
        metadata={"month": month, "year": year},
    )

    logger.info(f"Auto half-day deduction for user={user.id}, month={month}/{year}")
