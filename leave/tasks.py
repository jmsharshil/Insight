import logging
from decimal import Decimal
from django.utils import timezone
from .models import LeaveBalance, LEAVE_TYPE_CHOICES
from django.contrib.auth import get_user_model

logger = logging.getLogger(__name__)

def accrue_monthly_leaves_task():
    """
    Runs daily via the scheduler. On the 1st of every month, 
    it adds 1.5 days to the 'casual' leave balance (or 'paid' if preferred) 
    for all active staff members.
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
    ]
    
    staff_members = User.objects.filter(role__in=staff_roles, is_active=True)
    leave_type_to_accrue = 'casual'  # As per standard
    
    accrued_amount = Decimal('1.5')
    updated_count = 0
    
    current_year = today.year
    if today.month < 4:
        financial_year = current_year - 1
    else:
        financial_year = current_year
        
    for user in staff_members:
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
        
    logger.info(f"[LEAVE ACCRUAL] Successfully accrued {accrued_amount} days of {leave_type_to_accrue} leave for {updated_count} users.")
