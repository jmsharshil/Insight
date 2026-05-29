from django.contrib import admin
from .models import (
    Course, Subject, Batch, BatchStudent, BatchFaculty,
    Classroom, TimetableSlot,
)


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'course_type', 'duration_months', 'fee_amount', 'is_active', 'created_at']
    list_filter = ['course_type', 'is_active']
    search_fields = ['name', 'code']
    ordering = ['name']
    list_editable = ['is_active']


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'course', 'total_hours', 'is_active', 'created_at']
    list_filter = ['is_active', 'course']
    search_fields = ['name', 'code']
    ordering = ['name']
    list_editable = ['is_active']


@admin.register(Batch)
class BatchAdmin(admin.ModelAdmin):
    list_display = ['batch_code', 'name', 'course', 'start_date', 'end_date', 'max_students', 'is_active', 'created_at']
    list_filter = ['is_active', 'course', 'group_module', 'batch_attempt']
    search_fields = ['name', 'batch_code']
    ordering = ['-created_at']
    list_editable = ['is_active']
    date_hierarchy = 'start_date'


@admin.register(BatchStudent)
class BatchStudentAdmin(admin.ModelAdmin):
    list_display = ['student', 'batch', 'enrolled_at']
    list_filter = ['batch']
    search_fields = ['student__name', 'student__email', 'batch__batch_code']
    ordering = ['-enrolled_at']
    date_hierarchy = 'enrolled_at'


@admin.register(BatchFaculty)
class BatchFacultyAdmin(admin.ModelAdmin):
    list_display = ['faculty', 'batch', 'subject', 'assigned_at']
    list_filter = ['batch', 'subject']
    search_fields = ['faculty__name', 'faculty__email', 'batch__batch_code']
    ordering = ['-assigned_at']
    date_hierarchy = 'assigned_at'


@admin.register(Classroom)
class ClassroomAdmin(admin.ModelAdmin):
    list_display = ['name', 'capacity', 'is_active', 'created_at']
    list_filter = ['is_active']
    search_fields = ['name']
    ordering = ['name']
    list_editable = ['is_active']


@admin.register(TimetableSlot)
class TimetableSlotAdmin(admin.ModelAdmin):
    list_display = ['batch', 'subject', 'faculty', 'classroom', 'day_of_week', 'start_time', 'end_time', 'session']
    list_filter = ['batch', 'session', 'day_of_week']
    search_fields = ['batch__batch_code', 'faculty__name', 'subject__name']
    ordering = ['day_of_week', 'start_time']
