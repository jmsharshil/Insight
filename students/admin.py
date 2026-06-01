from django.contrib import admin
from .models import Student, ParentLink, BatchHistory, InventoryIssue, DigitalIDCard, StudentStatusHistory


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ('admission_number', 'first_name', 'surname', 'branch', 'batch', 'status', 'is_active', 'qr_blocked')
    list_filter = ('status', 'is_active', 'qr_blocked', 'branch')
    search_fields = ('admission_number', 'first_name', 'surname', 'email', 'roll_number')
    readonly_fields = ('admission_number', 'created_at', 'updated_at')


@admin.register(ParentLink)
class ParentLinkAdmin(admin.ModelAdmin):
    list_display = ('student', 'parent', 'relationship', 'is_primary')


@admin.register(BatchHistory)
class BatchHistoryAdmin(admin.ModelAdmin):
    list_display = ('student', 'batch_name', 'changed_at', 'changed_by')


@admin.register(InventoryIssue)
class InventoryIssueAdmin(admin.ModelAdmin):
    list_display = ('student', 'item_type', 'quantity', 'issued_at')


@admin.register(DigitalIDCard)
class DigitalIDCardAdmin(admin.ModelAdmin):
    list_display = ('student', 'is_active', 'generated_at')


@admin.register(StudentStatusHistory)
class StudentStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ('student', 'old_status', 'new_status', 'changed_at')