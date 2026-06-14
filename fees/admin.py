from django.contrib import admin
from fees.models import *

@admin.register(FeeStructure)
class FeeStructureAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'course', 'batch', 'total_amount', 'description', 'is_active', 'created_by', 'created_at', 'updated_at',)
    search_fields = ('name', 'description')
    list_filter = ('course', 'updated_at', 'created_by', 'batch', 'created_at', 'is_active',)
    ordering = ['-created_at']
    list_editable = ('total_amount', 'is_active',)


@admin.register(StudentFee)
class StudentFeeAdmin(admin.ModelAdmin):
    list_display = ('id', 'student', 'fee_structure', 'total_amount', 'discount', 'discount_reason', 'amount_paid', 'status', 'due_date', 'created_at',)
    list_filter = ('due_date', 'status', 'updated_at', 'fee_structure', 'created_at', 'student',)
    search_fields = ['student__first_name', 'student__surname', 'student__email', 'fee_structure__name']
    ordering = ['-created_at']
    date_hierarchy = 'due_date'
    list_editable = ('total_amount', 'discount', 'discount_reason', 'amount_paid', 'status', 'due_date',)

@admin.register(InstallmentPlan)
class InstallmentPlanAdmin(admin.ModelAdmin):
    list_display = ('id', 'student_fee', 'created_by', 'status', 'approved_by', 'approved_at', 'rejection_reason', 'created_at',)
    list_filter = ('student_fee', 'status', 'approved_at', 'created_by', 'created_at', 'approved_by',)

@admin.register(InstallmentItem)
class InstallmentItemAdmin(admin.ModelAdmin):
    list_display = ('id', 'plan', 'amount', 'due_date', 'is_paid', 'paid_at',)
    list_filter = ('is_paid', 'due_date', 'paid_at', 'plan',)

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('id', 'student', 'student_fee', 'installment_item', 'amount', 'payment_mode', 'transaction_ref', 'payment_proof', 'status', 'receipt_number',)
    list_filter = ('verified_at', 'installment_item', 'verified_by', 'student_fee', 'status', 'updated_at', 'recorded_by', 'payment_date',)

@admin.register(Refund)
class RefundAdmin(admin.ModelAdmin):
    list_display = ('id', 'payment', 'amount', 'reason', 'processed_by', 'status', 'created_at',)
    list_filter = ('payment', 'created_at', 'status', 'processed_by',)

@admin.register(BankAccount)
class BankAccountAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'bank_name', 'account_number', 'ifsc_code', 'branch_name', 'is_active', 'created_at',)
    search_fields = ('name',)
    list_filter = ('created_at', 'is_active',)
