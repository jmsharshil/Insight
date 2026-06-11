from django.contrib import admin
from batches.models import *

@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ('id', 'organization', 'name', 'code', 'course_type', 'duration_months', 'fee_amount', 'description', 'is_active', 'created_at',)
    search_fields = ('name', 'code',)
    list_filter = ('course_type', 'organization', 'updated_at', 'created_at', 'is_active',)

@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ('id', 'organization', 'level', 'name', 'code', 'total_hours', 'is_active', 'created_at',)
    search_fields = ('name', 'code',)
    list_filter = ('created_at', 'organization', 'level', 'is_active',)

@admin.register(Batch)
class BatchAdmin(admin.ModelAdmin):
    list_display = ('id', 'organization', 'branch', 'course', 'name', 'batch_code', 'group_module', 'batch_attempt', 'location', 'start_date',)
    search_fields = ('name',)
    list_filter = ('organization', 'branch', 'group_module', 'updated_at', 'start_date', 'end_date', 'created_at', 'course',)

@admin.register(BatchStudent)
class BatchStudentAdmin(admin.ModelAdmin):
    list_display = ('id', 'batch', 'student', 'enrolled_at',)
    list_filter = ('enrolled_at', 'batch', 'student',)

@admin.register(BatchSequenceCounter)
class BatchSequenceCounterAdmin(admin.ModelAdmin):
    list_display = ('id', 'course_type', 'batch_attempt', 'attempt_year', 'last_sequence',)

@admin.register(BatchFaculty)
class BatchFacultyAdmin(admin.ModelAdmin):
    list_display = ('id', 'batch', 'faculty', 'subject', 'assigned_at',)
    list_filter = ('batch', 'assigned_at', 'subject', 'faculty',)

@admin.register(Classroom)
class ClassroomAdmin(admin.ModelAdmin):
    list_display = ('id', 'organization', 'name', 'capacity', 'is_active', 'created_at',)
    search_fields = ('name',)
    list_filter = ('created_at', 'organization', 'is_active',)

@admin.register(CourseLevel)
class CourseLevelAdmin(admin.ModelAdmin):
    list_display = ('id', 'organization', 'course', 'name', 'order', 'description', 'is_active',)
    search_fields = ('name',)
    list_filter = ('course', 'organization', 'is_active',)

@admin.register(Chapter)
class ChapterAdmin(admin.ModelAdmin):
    list_display = ('id', 'subject', 'name', 'order', 'description', 'is_active',)
    search_fields = ('name',)
    list_filter = ('subject', 'is_active',)

@admin.register(TimetableExamType)
class TimetableExamTypeAdmin(admin.ModelAdmin):
    list_display = ('id', 'organization', 'name', 'description', 'is_active', 'created_at',)
    search_fields = ('name',)
    list_filter = ('created_at', 'organization', 'is_active',)

@admin.register(TimetableSlot)
class TimetableSlotAdmin(admin.ModelAdmin):
    list_display = ('id', 'organization', 'batch', 'subject', 'faculty', 'classroom', 'day_of_week', 'start_time', 'end_time', 'session',)
    list_filter = ('organization', 'subject', 'session_type', 'session', 'is_recurring', 'classroom', 'chapter', 'faculty',)
    search_fields = ['batch__batch_code', 'faculty__name', 'subject__name']
    ordering = ['day_of_week', 'start_time']
