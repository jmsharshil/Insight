from django.contrib import admin
from exams.models import *

@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    list_display = ('id', 'branch', 'batch', 'subject', 'title', 'exam_type', 'total_marks', 'pass_marks', 'duration_minutes', 'scheduled_date', 'status')
    search_fields = ('title',)
    list_filter = ('is_deleted', 'exam_type', 'status', 'screen_lock_action', 'branch', 'subject', 'created_by', 'scheduled_date',)
    filter_horizontal = ('paper_checkers',)
    raw_id_fields = ('faculty', 'batch', 'subject', 'created_by')
    readonly_fields = ('total_marks',)

@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ('id', 'exam', 'question_text', 'question_type', 'marks', 'order', 'image',)
    list_filter = ('exam', 'question_type',)

@admin.register(Choice)
class ChoiceAdmin(admin.ModelAdmin):
    list_display = ('id', 'question', 'choice_text', 'is_correct',)
    list_filter = ('question', 'is_correct',)

@admin.register(ExamSession)
class ExamSessionAdmin(admin.ModelAdmin):
    list_display = ('id', 'exam', 'student', 'started_at', 'submitted_at', 'is_submitted', 'auto_submitted', 'ip_address', 'device_fingerprint', 'student_lat',)
    list_filter = ('started_at', 'last_geo_check_at', 'submitted_at', 'exam', 'auto_submitted', 'is_submitted', 'student',)

@admin.register(StudentAnswer)
class StudentAnswerAdmin(admin.ModelAdmin):
    list_display = ('id', 'session', 'question', 'selected_choice', 'text_answer', 'answered_at',)
    list_filter = ('session', 'selected_choice', 'question', 'answered_at',)

@admin.register(SeatArrangement)
class SeatArrangementAdmin(admin.ModelAdmin):
    list_display = ('id', 'exam', 'student', 'room_name', 'seat_number', 'row_number', 'assigned_by',)
    list_filter = ('assigned_by', 'student', 'exam',)

@admin.register(MalpracticeReport)
class MalpracticeReportAdmin(admin.ModelAdmin):
    list_display = ('id', 'exam', 'student', 'reported_by', 'description', 'severity', 'reported_at', 'action_taken',)
    list_filter = ('exam', 'severity', 'reported_at', 'student', 'reported_by',)

@admin.register(ScreenEvent)
class ScreenEventAdmin(admin.ModelAdmin):
    list_display = ('id', 'session', 'event_type', 'occurred_at', 'action_taken',)
    list_filter = ('session', 'action_taken', 'event_type', 'occurred_at',)

@admin.register(CheckerToken)
class CheckerTokenAdmin(admin.ModelAdmin):
    list_display = ('id', 'marksheet', 'token', 'created_at', 'expires_at', 'is_used',)
    list_filter = ('marksheet', 'created_at', 'expires_at', 'is_used',)

@admin.register(AnswerKeyDistributionLog)
class AnswerKeyDistributionLogAdmin(admin.ModelAdmin):
    list_display = ('id', 'exam', 'sent_to', 'sent_at', 'link_expires',)
    list_filter = ('link_expires', 'sent_to', 'exam', 'sent_at',)
