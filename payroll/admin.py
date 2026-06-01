from django.contrib import admin
from .models import LateEntryPolicy, PayrollRun, PaySlip, SessionLatePenaltyLog


@admin.register(LateEntryPolicy)
class LateEntryPolicyAdmin(admin.ModelAdmin):
    list_display = ['branch', 'grace_period_minutes', 'deduction_per_minute',
                    'absence_deduction_per_day', 'late_entry_threshold',
                    'auto_halfday_deduction', 'is_active']


@admin.register(PayrollRun)
class PayrollRunAdmin(admin.ModelAdmin):
    list_display = ['branch', 'month', 'year', 'status', 'total_amount', 'generated_at']
    list_filter = ['status', 'year']


@admin.register(PaySlip)
class PaySlipAdmin(admin.ModelAdmin):
    list_display = ['faculty', 'faculty_profile', 'net_salary', 'absence_deductions', 'is_disbursed']
    list_filter = ['is_disbursed']


@admin.register(SessionLatePenaltyLog)
class SessionLatePenaltyLogAdmin(admin.ModelAdmin):
    list_display = ['payslip', 'late_minutes', 'penalty_amount', 'grace_applied']
