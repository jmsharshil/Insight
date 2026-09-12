from django.contrib import admin
from batches.models import *

@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ('id', 'organization', 'name', 'code', 'description', 'is_active', 'created_at',)
    search_fields = ('name', 'code', 'description')
    list_filter = ('organization', 'updated_at', 'created_at', 'is_active',)
    ordering = ['name']
    list_editable = ['is_active']

@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ('id', 'organization', 'level', 'name', 'code', 'total_hours', 'is_active', 'created_at',)
    list_filter = ('created_at', 'organization', 'level', 'is_active',)
    list_editable = ['is_active']
    readonly_fields = ('total_hours', 'code', 'created_at')
    ordering = ['name']
    search_fields = ('name', 'description', 'code',)

@admin.register(Batch)
class BatchAdmin(admin.ModelAdmin):
    list_display = ('id', 'organization', 'branch', 'course', 'name', 'batch_code', 'group_module', 'batch_attempt', 'start_date', 'is_active',)
    list_filter = ('organization', 'branch', 'group_module', 'updated_at', 'start_date', 'end_date', 'created_at', 'course',)
    list_editable = ['is_active']
    date_hierarchy = 'start_date'
    ordering = ['name', '-created_at']
    search_fields = ('name', 'description', 'code', 'batch_code',)
    autocomplete_fields = ['course', 'branch']

@admin.register(BatchStudent)
class BatchStudentAdmin(admin.ModelAdmin):
    list_display = ('id', 'batch', 'student', 'enrolled_at',)
    list_filter = ('enrolled_at', 'batch', 'student',)
    search_fields = ('batch__batch_code', 'student__name', 'student__mobile_number', 'student__email',)
    ordering = ['-enrolled_at']
    date_hierarchy = 'enrolled_at'
    autocomplete_fields = ['batch', 'student']

@admin.register(BatchSequenceCounter)
class BatchSequenceCounterAdmin(admin.ModelAdmin):
    list_display = ('id', 'course_type', 'batch_attempt', 'attempt_year', 'last_sequence',)

@admin.register(BatchFaculty)
class BatchFacultyAdmin(admin.ModelAdmin):
    list_display = ('id', 'batch', 'faculty', 'subject', 'assigned_at',)
    list_filter = ('batch', 'assigned_at', 'subject', 'faculty',)
    search_fields = ('batch__batch_code', 'subject__name',)
    ordering = ['-assigned_at']
    date_hierarchy = 'assigned_at'
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "subject":
            # Filter subjects to only those belonging to the same organization as the selected faculty's branch
            if "faculty" in request.GET:
                faculty_id = request.GET.get("faculty")
                try:
                    from faculty.models import FacultyProfile
                    faculty = FacultyProfile.objects.select_related("branch__organization").get(id=faculty_id)
                    if faculty.branch and faculty.branch.organization:
                        kwargs["queryset"] = Subject.objects.filter(
                            organization=faculty.branch.organization
                        )
                    else:
                        kwargs["queryset"] = Subject.objects.none()
                except (FacultyProfile.DoesNotExist, Exception):
                    kwargs["queryset"] = Subject.objects.all()
            else:
                kwargs["queryset"] = Subject.objects.all()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

@admin.register(Classroom)
class ClassroomAdmin(admin.ModelAdmin):
    list_display = ('id', 'organization', 'name', 'capacity', 'is_active', 'created_at',)
    list_filter = ('created_at', 'organization', 'is_active',)
    search_fields = ('name',)
    ordering = ['name']
    list_editable = ['is_active']

@admin.register(CourseLevel)
class CourseLevelAdmin(admin.ModelAdmin):
    list_display = ('id', 'organization', 'course', 'name', 'course_type', 'duration_months', 'fee_amount', 'order', 'description', 'is_active',)
    search_fields = ('name',)
    list_filter = ('course', 'course_type', 'organization', 'is_active',)

@admin.register(Chapter)
class ChapterAdmin(admin.ModelAdmin):
    list_display = ('id', 'subject', 'name', 'order', 'duration_hours', 'description', 'is_active',)
    search_fields = ('name', 'description')
    list_filter = ('subject', 'is_active',)
    list_editable = ('duration_hours', 'is_active', 'order')
    filter_horizontal = ('faculties',)


@admin.register(TimetableSlot)
class TimetableSlotAdmin(admin.ModelAdmin):
    list_display = ('id', 'organization', 'batch', 'subject', 'faculty', 'classroom', 'day_of_week', 'start_time', 'end_time',)
    list_filter = ('organization', 'subject', 'session_type', 'is_recurring', 'classroom', 'chapters', 'faculty',)
    search_fields = ('batch__batch_code', 'subject__name',)
    ordering = ['day_of_week', 'start_time']
