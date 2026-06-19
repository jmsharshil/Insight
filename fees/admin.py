from django.contrib import admin
from fees.models import *

@admin.register(FeeStructure)
class FeeStructureAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'course', 'batch', 'total_amount', 'icsi_registration_fees',
                    'icsi_exam_fees', 'token_amount', 'description', 'is_active',
                    'created_by', 'created_at',)
    search_fields = ('name', 'description')
    list_filter = ('course', 'updated_at', 'created_by', 'batch', 'created_at', 'is_active',)
    ordering = ['-created_at']
    list_editable = ('icsi_registration_fees', 'icsi_exam_fees', 'token_amount', 'is_active',)
    readonly_fields = ('total_amount',)


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
    list_display = (
        'id', 'student', 'student_fee', 'amount', 'payment_mode',
        'transaction_ref', 'status', 'receipt_number', 'payment_date',
        'payment_proof', 'payment_document', 'verified_by', 'verified_at',
        'recorded_by', 'note',
    )
    list_filter = (
        'status', 'payment_mode', 'payment_date', 'verified_at',
        'student_fee', 'recorded_by', 'verified_by',
    )
    search_fields = ('receipt_number', 'transaction_ref', 'student__first_name', 'student__surname', 'note')
    ordering = ['-created_at']
    date_hierarchy = 'payment_date'

@admin.register(Refund)
class RefundAdmin(admin.ModelAdmin):
    list_display = ('id', 'payment', 'amount', 'reason', 'processed_by', 'status', 'created_at',)
    list_filter = ('payment', 'created_at', 'status', 'processed_by',)

@admin.register(BankAccount)
class BankAccountAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'bank_name', 'account_number', 'ifsc_code', 'branch_name', 'is_active', 'created_at', 'max_payment_amount')
    search_fields = ('name',)
    list_filter = ('created_at', 'is_active',)
