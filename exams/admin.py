from django.contrib import admin
from .models import (
    Exam, Question, Choice, ExamSession, StudentAnswer,
    SeatArrangement, MalpracticeReport, ScreenEvent,
    CheckerToken, AnswerKeyDistributionLog,
)


@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    list_display = ['title', 'exam_type', 'batch', 'branch', 'scheduled_date', 'status', 'is_deleted']
    list_filter = ['exam_type', 'status', 'is_deleted', 'scheduled_date']
    search_fields = ['title']


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ['exam', 'order', 'question_type', 'marks']
    list_filter = ['question_type']


@admin.register(Choice)
class ChoiceAdmin(admin.ModelAdmin):
    list_display = ['question', 'choice_text', 'is_correct']


@admin.register(ExamSession)
class ExamSessionAdmin(admin.ModelAdmin):
    list_display = ['exam', 'student', 'started_at', 'is_submitted', 'auto_submitted']
    list_filter = ['is_submitted', 'auto_submitted']


@admin.register(StudentAnswer)
class StudentAnswerAdmin(admin.ModelAdmin):
    list_display = ['session', 'question', 'answered_at']


@admin.register(SeatArrangement)
class SeatArrangementAdmin(admin.ModelAdmin):
    list_display = ['exam', 'student', 'room_name', 'seat_number']


@admin.register(MalpracticeReport)
class MalpracticeReportAdmin(admin.ModelAdmin):
    list_display = ['exam', 'student', 'severity', 'reported_at']
    list_filter = ['severity']


@admin.register(ScreenEvent)
class ScreenEventAdmin(admin.ModelAdmin):
    list_display = ['session', 'event_type', 'action_taken', 'occurred_at']


@admin.register(CheckerToken)
class CheckerTokenAdmin(admin.ModelAdmin):
    list_display = ['marksheet', 'is_used', 'created_at', 'expires_at']


@admin.register(AnswerKeyDistributionLog)
class AnswerKeyDistributionLogAdmin(admin.ModelAdmin):
    list_display = ['exam', 'sent_to', 'sent_at', 'link_expires']
