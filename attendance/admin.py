from django.contrib import admin
from .models import AttendanceRecord, QRScanLog, AlertLog, ViolationRecord


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ('student', 'batch', 'date', 'session', 'status', 'checked_in_at', 'checked_out_at', 'marked_by', 'is_corrected')
    list_filter = ('status', 'session', 'date', 'is_corrected')
    search_fields = ('student__user__name', 'student__roll_number')
    readonly_fields = ('id', 'marked_at')


@admin.register(QRScanLog)
class QRScanLogAdmin(admin.ModelAdmin):
    list_display = ('student', 'scan_type', 'scanned_at', 'is_valid', 'scanned_by')
    list_filter = ('scan_type', 'is_valid')
    search_fields = ('student__user__name', 'student__roll_number')
    readonly_fields = ('id', 'scanned_at')


@admin.register(AlertLog)
class AlertLogAdmin(admin.ModelAdmin):
    list_display = ('student', 'alert_type', 'threshold', 'current_pct', 'sent_at', 'notified_parent', 'notified_admin')
    list_filter = ('alert_type', 'notified_parent', 'notified_admin')
    search_fields = ('student__user__name',)
    readonly_fields = ('id', 'sent_at')


@admin.register(ViolationRecord)
class ViolationRecordAdmin(admin.ModelAdmin):
    list_display = ('student', 'violation_type', 'date', 'is_resolved', 'resolved_by', 'resolved_at')
    list_filter = ('violation_type', 'is_resolved', 'date')
    search_fields = ('student__user__name', 'student__roll_number')
    readonly_fields = ('id', 'created_at')
