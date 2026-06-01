from django.contrib import admin
from .models import StudentProfile


@admin.register(StudentProfile)
class StudentProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'roll_number', 'branch', 'batch', 'is_active', 'qr_blocked')
    list_filter = ('is_active', 'qr_blocked')
    search_fields = ('user__name', 'roll_number')