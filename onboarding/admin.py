from django.contrib import admin
from onboarding.models import *

@admin.register(Admission)
class AdmissionAdmin(admin.ModelAdmin):
    list_display = ('id', 'lead', 'branch', 'first_name', 'surname', 'father_name', 'mother_name', 'dob', 'category', 'email',)
    search_fields = ('email',)
    list_filter = ('submitted_at', 'tenth_medium', 'status', 'lead', 'dob', 'branch', 'group_module', 'consent',)

@admin.register(AdmissionStatusHistory)
class AdmissionStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ('id', 'admission', 'status', 'changed_by', 'note', 'changed_at',)
    list_filter = ('changed_by', 'status', 'admission', 'changed_at',)
