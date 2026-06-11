from django.contrib import admin
from leads.models import *

@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ('id', 'branch', 'form_type', 'first_name', 'email', 'phone_student', 'course', 'group_module', 'batch_attempt', 'location',)
    search_fields = ('email',)
    list_filter = ('followup_set_at', 'tenth_medium', 'interested_at', 'branch', 'lost_at', 'group_module', 'followup_date', 'twelfth_medium',)

@admin.register(LeadStage)
class LeadStageAdmin(admin.ModelAdmin):
    list_display = ('id', 'lead', 'stage', 'changed_by', 'note', 'changed_at',)
    list_filter = ('changed_by', 'lead', 'changed_at', 'stage',)
