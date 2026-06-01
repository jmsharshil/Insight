from django.contrib import admin
from .models import MarkSheet, SubmissionReminderLog, PublishedResult


@admin.register(MarkSheet)
class MarkSheetAdmin(admin.ModelAdmin):
    list_display = ['exam', 'student', 'paper_checker', 'marks_obtained', 'is_pass', 'is_submitted']
    list_filter = ['is_submitted', 'is_pass', 'is_rechecked']


@admin.register(SubmissionReminderLog)
class SubmissionReminderLogAdmin(admin.ModelAdmin):
    list_display = ['marksheet', 'sent_at', 'reminder_count']


@admin.register(PublishedResult)
class PublishedResultAdmin(admin.ModelAdmin):
    list_display = ['exam', 'student', 'marks_obtained', 'total_marks', 'percentage', 'rank', 'is_pass']
    list_filter = ['is_pass']
