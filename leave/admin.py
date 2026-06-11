from django.contrib import admin
from leave.models import *

@admin.register(PublicHoliday)
class PublicHolidayAdmin(admin.ModelAdmin):
    list_display = ('id', 'branch', 'date', 'name', 'year', 'created_by', 'created_at',)
    search_fields = ('name',)
    list_filter = ('created_by', 'date', 'created_at', 'branch',)

@admin.register(LeavePolicy)
class LeavePolicyAdmin(admin.ModelAdmin):
    list_display = ('id', 'branch', 'leave_type', 'annual_quota', 'max_club_days', 'carry_forward', 'max_carry_days', 'min_advance_days', 'allow_half_day', 'sandwich_rule',)
    list_filter = ('leave_type', 'branch', 'sandwich_rule', 'allow_half_day', 'carry_forward', 'is_active',)

@admin.register(LeaveBalance)
class LeaveBalanceAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'leave_type', 'year', 'total_days', 'used_days', 'carried_forward',)
    list_filter = ('leave_type', 'user',)

@admin.register(LeaveApplication)
class LeaveApplicationAdmin(admin.ModelAdmin):
    list_display = ('id', 'applied_by', 'branch', 'leave_type', 'from_date', 'to_date', 'is_half_day', 'half_day_session', 'total_days', 'reason',)
    list_filter = ('second_approver', 'first_approved_at', 'second_approved_at', 'status', 'leave_type', 'branch', 'from_date', 'reviewed_at',)

@admin.register(LateEntryRecord)
class LateEntryRecordAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'branch', 'date', 'expected_time', 'actual_time', 'late_minutes', 'grace_minutes', 'is_penalized', 'penalty_type',)
    list_filter = ('auto_deduction_triggered', 'branch', 'recorded_by', 'is_penalized', 'penalty_type', 'date', 'created_at', 'user',)
