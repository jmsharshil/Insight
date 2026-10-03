from django.contrib import admin
from leads.models import Lead, LeadStage, LeadAssignmentLog, SalesDailyPlan, SalesDailyActivity

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

@admin.register(SalesDailyPlan)
class SalesDailyPlanAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'plan_date', 'description', 'created_at',)
    list_filter = ('plan_date', 'user',)
    search_fields = ('user__name', 'user__email', 'description',)

@admin.register(SalesDailyActivity)
class SalesDailyActivityAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'plan', 'activity_date', 'notes', 'created_at',)
    list_filter = ('activity_date', 'user',)
    search_fields = ('user__name', 'user__email', 'notes',)


from leads.models import LeadTransferRequest, SalesDailyActivityTiming, SalesActivityPhoto, OdometerReading, SalesPlanReminder

@admin.register(LeadTransferRequest)
class LeadTransferRequestAdmin(admin.ModelAdmin):
    list_display = ('id', 'lead', 'requested_by', 'assigned_to', 'status', 'created_at')
    list_filter = ('status', 'requested_by', 'assigned_to')
    search_fields = ('lead__first_name', 'lead__email', 'reason')

@admin.register(SalesDailyActivityTiming)
class SalesDailyActivityTimingAdmin(admin.ModelAdmin):
    list_display = ('id', 'activity', 'date', 'start_time', 'end_time')
    list_filter = ('date', 'activity__user')

@admin.register(SalesActivityPhoto)
class SalesActivityPhotoAdmin(admin.ModelAdmin):
    list_display = ('id', 'activity', 'photo_type', 'captured_at')
    list_filter = ('photo_type', 'captured_at')
    search_fields = ('activity__user__name', 'activity__user__email')

@admin.register(OdometerReading)
class OdometerReadingAdmin(admin.ModelAdmin):
    list_display = ('id', 'activity', 'total_kms', 'status', 'approved_by', 'created_at')
    list_filter = ('status', 'approved_by', 'created_at')
    search_fields = ('activity__user__name', 'activity__user__email')

@admin.register(SalesPlanReminder)
class SalesPlanReminderAdmin(admin.ModelAdmin):
    list_display = ('id', 'plan', 'purpose', 'reminder_time', 'is_sent')
    list_filter = ('is_sent', 'reminder_time')
