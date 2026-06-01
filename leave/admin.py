from django.contrib import admin
from .models import LeavePolicy, LeaveBalance, LeaveApplication, LateEntryRecord, PublicHoliday


@admin.register(PublicHoliday)
class PublicHolidayAdmin(admin.ModelAdmin):
    list_display = ['name', 'date', 'branch', 'year']
    list_filter = ['year', 'branch']
    search_fields = ['name']


@admin.register(LeavePolicy)
class LeavePolicyAdmin(admin.ModelAdmin):
    list_display = ['branch', 'leave_type', 'annual_quota', 'sandwich_rule', 'is_active']
    list_filter = ['leave_type', 'is_active']


@admin.register(LeaveBalance)
class LeaveBalanceAdmin(admin.ModelAdmin):
    list_display = ['user', 'leave_type', 'year', 'total_days', 'used_days']
    list_filter = ['leave_type', 'year']


@admin.register(LeaveApplication)
class LeaveApplicationAdmin(admin.ModelAdmin):
    list_display = ['applied_by', 'leave_type', 'from_date', 'to_date', 'total_days', 'status', 'is_auto_generated']
    list_filter = ['status', 'leave_type', 'is_auto_generated']


@admin.register(LateEntryRecord)
class LateEntryRecordAdmin(admin.ModelAdmin):
    list_display = ['user', 'date', 'late_minutes', 'is_penalized', 'penalty_type', 'auto_deduction_triggered']
    list_filter = ['is_penalized', 'auto_deduction_triggered']
