from django.contrib import admin
from payroll.models import *

@admin.register(LateEntryPolicy)
class LateEntryPolicyAdmin(admin.ModelAdmin):
    list_display = ('id', 'branch', 'grace_period_minutes', 'deduction_per_minute', 'max_deduction_per_session', 'absence_deduction_per_day', 'late_entry_threshold', 'auto_halfday_deduction', 'is_active', 'created_by',)
    list_filter = ('branch', 'created_by', 'auto_halfday_deduction', 'updated_at', 'is_active',)

@admin.register(PayrollRun)
class PayrollRunAdmin(admin.ModelAdmin):
    list_display = ('id', 'branch', 'month', 'year', 'status', 'generated_by', 'approved_by', 'generated_at', 'approved_at', 'disbursed_at',)
    list_filter = ('status', 'generated_at', 'branch', 'approved_at', 'generated_by', 'disbursed_at', 'approved_by',)

@admin.register(PaySlip)
class PaySlipAdmin(admin.ModelAdmin):
    list_display = ('id', 'payroll_run', 'faculty', 'basic_salary', 'total_session_hours', 'hour_based_amount', 'late_penalty', 'absence_deductions', 'leave_deductions', 'other_deductions',)
    list_filter = ('is_disbursed', 'faculty', 'payroll_run',)

@admin.register(SessionLatePenaltyLog)
class SessionLatePenaltyLogAdmin(admin.ModelAdmin):
    list_display = ('id', 'payslip', 'session_report', 'scheduled_time', 'actual_start', 'late_minutes', 'penalty_amount', 'grace_applied',)
    list_filter = ('grace_applied', 'session_report', 'payslip',)
