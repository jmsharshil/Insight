from django.contrib import admin
from .models import FacultyProfile, FacultyQRScanLog, SessionReport, SubjectHourlyRate


@admin.register(FacultyProfile)
class FacultyProfileAdmin(admin.ModelAdmin):
    list_display = ['employee_id', 'user', 'branch', 'level', 'employment_type', 'is_active']
    list_filter = ['level', 'employment_type', 'is_active']
    search_fields = ['employee_id', 'user__name', 'specialization']


@admin.register(SubjectHourlyRate)
class SubjectHourlyRateAdmin(admin.ModelAdmin):
    list_display = ['faculty', 'subject', 'hourly_rate', 'effective_from']
    list_filter = ['effective_from']


@admin.register(FacultyQRScanLog)
class FacultyQRScanLogAdmin(admin.ModelAdmin):
    list_display = ['faculty', 'scan_type', 'scanned_at', 'is_late', 'late_minutes']
    list_filter = ['scan_type', 'is_late']


@admin.register(SessionReport)
class SessionReportAdmin(admin.ModelAdmin):
    list_display = ['faculty', 'batch', 'subject', 'session_date', 'status', 'completion_percentage', 'duration_minutes']
    list_filter = ['status', 'session_date']
    search_fields = ['chapter_covered']
