from django.contrib import admin
from students.models import *

@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ('id', 'admission_number', 'admission', 'user', 'branch', 'current_batch_name', 'batch', 'roll_number', 'is_active', 'qr_blocked',)
    search_fields = ('email',)
    list_filter = ('enrolled_at', 'created_at', 'blood_group', 'status', 'branch', 'dob', 'qr_blocked', 'updated_at',)

@admin.register(ParentLink)
class ParentLinkAdmin(admin.ModelAdmin):
    list_display = ('id', 'student', 'parent', 'relationship', 'is_primary', 'linked_at',)
    list_filter = ('student', 'parent', 'linked_at', 'relationship', 'is_primary',)

@admin.register(BatchHistory)
class BatchHistoryAdmin(admin.ModelAdmin):
    list_display = ('id', 'student', 'batch_name', 'reason', 'changed_by', 'changed_at',)
    list_filter = ('changed_by', 'changed_at', 'student',)

@admin.register(InventoryIssue)
class InventoryIssueAdmin(admin.ModelAdmin):
    list_display = ('id', 'student', 'item_type', 'item_name', 'quantity', 'size', 'isbn', 'issued_by', 'issued_at', 'returned_at',)
    list_filter = ('issued_by', 'issued_at', 'item_type', 'returned_at', 'student',)

@admin.register(DigitalIDCard)
class DigitalIDCardAdmin(admin.ModelAdmin):
    list_display = ('id', 'student', 'qr_data', 'qr_image', 'card_image', 'is_active', 'generated_at', 'regenerated_at',)
    list_filter = ('regenerated_at', 'generated_at', 'student', 'is_active',)

@admin.register(StudentStatusHistory)
class StudentStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ('id', 'student', 'old_status', 'new_status', 'reason', 'changed_by', 'changed_at',)
    list_filter = ('new_status', 'changed_by', 'old_status', 'changed_at', 'student',)

@admin.register(StudentProfile)
class StudentProfileAdmin(admin.ModelAdmin):
    list_display = ('id', 'admission_number', 'admission', 'user', 'branch', 'current_batch_name', 'batch', 'roll_number', 'is_active', 'qr_blocked',)
    search_fields = ('email',)
    list_filter = ('enrolled_at', 'created_at', 'blood_group', 'status', 'branch', 'dob', 'qr_blocked', 'updated_at',)
