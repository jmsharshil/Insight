from django.contrib import admin
from attendance.models import *

@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ('id', 'student', 'batch', 'branch', 'date', 'status', 'checked_in_at', 'checked_out_at', 'marked_by',)
    list_filter = ('marked_at', 'is_corrected', 'status', 'branch', 'checked_out_at', 'checked_in_at', 'marked_by',)

@admin.register(QRScanLog)
class QRScanLogAdmin(admin.ModelAdmin):
    list_display = ('id', 'student', 'branch', 'scanned_at', 'scan_type', 'device_id', 'scanned_by', 'is_valid', 'invalid_reason', 'latitude',)
    list_filter = ('scan_type', 'is_valid', 'scanned_by', 'scanned_at', 'branch', 'time_verified', 'location_verified', 'timetable_slot',)

@admin.register(AlertLog)
class AlertLogAdmin(admin.ModelAdmin):
    list_display = ('id', 'student', 'alert_type', 'message', 'threshold', 'current_pct', 'sent_at', 'notified_parent', 'notified_admin',)
    list_filter = ('notified_admin', 'notified_parent', 'alert_type', 'sent_at', 'student',)
    search_fields = ('student__user__name', 'student__roll_number', 'message','notified_admin','notified_parent')
    list_display_links = ('id', 'student', 'message')
    readonly_fields = ('id', 'sent_at')

@admin.register(ViolationRecord)
class ViolationRecordAdmin(admin.ModelAdmin):
    list_display = ('id', 'student', 'violation_type', 'date', 'description', 'logged_by_admin', 'is_resolved', 'resolved_by', 'resolved_at', 'created_by')
    list_filter = ('resolved_by', 'resolved_at', 'logged_by_admin', 'violation_type', 'created_by', 'date', 'created_at', 'is_resolved')
    search_fields = ('student__user__name', 'student__roll_number')
    readonly_fields = ('id', 'created_at')
