from django.contrib import admin
from faculty.models import *
from batches.models import CourseLevel

@admin.register(FacultyProfile)
class FacultyProfileAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'branch', 'employee_id', 'photo', 'qualification', 'specialization', 'subject_expertise', 'level', 'employment_type',)
    list_filter = ('is_active', 'employment_type', 'branch', 'created_at', 'level', 'user', 'joining_date',)
    search_fields = ['employee_id', 'user__name', 'specialization']
    filter_horizontal = ('levels',)

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if db_field.name == "levels":
            # Ensure only levels from the same organization as the faculty's branch are selectable
            if request.user.is_superuser:
                kwargs["queryset"] = CourseLevel.objects.all()
            else:
                obj_id = request.resolver_match.kwargs.get("object_id") if hasattr(request, "resolver_match") else None
                if obj_id:
                    try:
                        faculty = FacultyProfile.objects.select_related("branch__organization").get(id=obj_id)
                        if faculty.branch and faculty.branch.organization:
                            kwargs["queryset"] = CourseLevel.objects.filter(
                                organization=faculty.branch.organization
                            )
                        else:
                            kwargs["queryset"] = CourseLevel.objects.none()
                    except FacultyProfile.DoesNotExist:
                        kwargs["queryset"] = CourseLevel.objects.none()
                else:
                    # For new faculty, default to current user's organization (if linked)
                    # Fallback to all for superusers or if no context
                    kwargs["queryset"] = CourseLevel.objects.all()
        return super().formfield_for_manytomany(db_field, request, **kwargs)


@admin.register(SubjectHourlyRate)
class SubjectHourlyRateAdmin(admin.ModelAdmin):
    list_display = ('id', 'faculty', 'subject', 'hourly_rate', 'effective_from', 'created_by', 'created_at',)
    list_filter = ('effective_from', 'subject', 'created_by', 'created_at', 'faculty',)

@admin.register(FacultyQRScanLog)
class FacultyQRScanLogAdmin(admin.ModelAdmin):
    list_display = ('id', 'faculty', 'branch', 'scanned_at', 'latitude', 'longitude', 'scan_type', 'is_late', 'late_minutes',)
    list_filter = ('scan_type', 'scanned_at', 'branch', 'is_late', 'faculty',)

@admin.register(SessionReport)
class SessionReportAdmin(admin.ModelAdmin):
    list_display = ('id', 'faculty', 'branch', 'batch', 'subject', 'timetable_slot', 'session_date', 'chapter_covered', 'topics_covered', 'completion_percentage',)
    list_filter = ('session_date', 'status', 'branch', 'subject', 'updated_at', 'timetable_slot', 'batch', 'created_at',)
    search_fields = ['chapter_covered']
