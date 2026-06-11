from django.contrib import admin
from results.models import *

@admin.register(MarkSheet)
class MarkSheetAdmin(admin.ModelAdmin):
    list_display = ('id', 'exam', 'student', 'paper_checker', 'marks_obtained', 'is_pass', 'remarks', 'checked_at', 'is_rechecked', 'recheck_request_at',)
    list_filter = ('recheck_request_at', 'exam', 'is_submitted', 'is_pass', 'paper_checker', 'is_rechecked', 'checked_at', 'student',)

@admin.register(RecheckRequest)
class RecheckRequestAdmin(admin.ModelAdmin):
    list_display = ('id', 'marksheet', 'requested_by', 'reason', 'status', 'reviewed_by', 'reviewed_at', 'new_checker', 'created_at',)
    list_filter = ('new_checker', 'marksheet', 'status', 'requested_by', 'reviewed_at', 'reviewed_by', 'created_at',)

@admin.register(SubmissionReminderLog)
class SubmissionReminderLogAdmin(admin.ModelAdmin):
    list_display = ('id', 'marksheet', 'sent_at', 'reminder_count',)
    list_filter = ('marksheet', 'sent_at',)

@admin.register(PublishedResult)
class PublishedResultAdmin(admin.ModelAdmin):
    list_display = ('id', 'exam', 'student', 'marks_obtained', 'total_marks', 'percentage', 'is_pass', 'rank', 'published_at', 'published_by',)
    list_filter = ('exam', 'is_pass', 'published_at', 'student', 'published_by',)
