from django.contrib import admin
from onboarding.models import *

@admin.register(Admission)
class AdmissionAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'first_name', 'surname', 'email', 'phone_student',
        'course', 'status', 'fee_structure', 'payment_amount',
        'transaction_id', 'payment_submitted_at', 'branch', 'lead',
        'assigned_counsellor', 'submitted_at',
    )
    search_fields = ('first_name', 'surname', 'email', 'phone_student', 'transaction_id')
    list_filter = (
        'status', 'branch', 'course', 'group_module', 'category',
        'fee_structure', 'submitted_at', 'payment_submitted_at',
        'assigned_counsellor',
    )
    readonly_fields = ('submitted_at', 'updated_at', 'payment_submitted_at')
    ordering = ['-submitted_at']

@admin.register(AdmissionStatusHistory)
class AdmissionStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ('id', 'admission', 'status', 'changed_by', 'note', 'changed_at',)
    list_filter = ('changed_by', 'status', 'admission', 'changed_at',)
