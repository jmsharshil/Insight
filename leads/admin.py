from django.contrib import admin
from leads.models import Lead, LeadStage, LeadAssignmentLog

@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ('id', 'branch', 'form_type', 'first_name', 'email', 'phone_student', 'course', 'group_module', 'batch_attempt', 'location', 'assigned_to', 'current_stage',)
    search_fields = ('email', 'first_name', 'surname', 'phone_student',)
    list_filter = ('followup_set_at', 'tenth_medium', 'interested_at', 'branch', 'lost_at', 'group_module', 'followup_date', 'twelfth_medium', 'assigned_to',)

@admin.register(LeadStage)
class LeadStageAdmin(admin.ModelAdmin):
    list_display = ('id', 'lead', 'stage', 'changed_by', 'note', 'changed_at',)
    list_filter = ('changed_by', 'lead', 'changed_at', 'stage',)

@admin.register(LeadAssignmentLog)
class LeadAssignmentLogAdmin(admin.ModelAdmin):
    list_display = ('id', 'lead', 'assigned_from', 'assigned_to', 'changed_by', 'note', 'changed_at',)
    list_filter = ('assigned_to', 'changed_by', 'changed_at',)
    readonly_fields = ('lead', 'assigned_from', 'assigned_to', 'changed_by', 'changed_at',)
