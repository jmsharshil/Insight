from django.contrib import admin
from .models import (
    FeeStructure, StudentFee,
    InstallmentPlan, InstallmentItem,
    Payment, Refund, BankAccount,
)


@admin.register(FeeStructure)
class FeeStructureAdmin(admin.ModelAdmin):
    list_display = ['name', 'course', 'batch', 'total_amount', 'is_active', 'created_at']
    list_filter = ['is_active', 'course']
    search_fields = ['name', 'description']
    ordering = ['-created_at']
    list_editable = ['is_active']


@admin.register(StudentFee)
class StudentFeeAdmin(admin.ModelAdmin):
    list_display = ['student', 'fee_structure', 'total_amount', 'discount', 'amount_paid', 'status', 'due_date', 'created_at']
    list_filter = ['status', 'due_date']
    search_fields = ['student__first_name', 'student__surname', 'student__email', 'fee_structure__name']
    ordering = ['-created_at']
    date_hierarchy = 'due_date'
    list_editable = ['status']


@admin.register(InstallmentPlan)
class InstallmentPlanAdmin(admin.ModelAdmin):
    list_display = ['student_fee', 'status', 'approved_by', 'approved_at', 'created_at']
    list_filter = ['status']
    search_fields = ['student_fee__student__first_name', 'student_fee__student__surname', 'student_fee__fee_structure__name']
    ordering = ['-created_at']
    date_hierarchy = 'created_at'


@admin.register(InstallmentItem)
class InstallmentItemAdmin(admin.ModelAdmin):
    list_display = ['plan', 'amount', 'due_date', 'is_paid', 'paid_at']
    list_filter = ['is_paid', 'due_date']
    search_fields = ['plan__student_fee__student__first_name', 'plan__student_fee__student__surname']
    ordering = ['due_date']
    date_hierarchy = 'due_date'
    list_editable = ['is_paid']


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ['receipt_number', 'student', 'student_fee', 'amount', 'payment_mode', 'status', 'payment_date', 'verified_at']
    list_filter = ['status', 'payment_mode', 'payment_date']
    search_fields = ['receipt_number', 'student__first_name', 'student__surname', 'student__email', 'transaction_ref']
    ordering = ['-created_at']
    date_hierarchy = 'payment_date'
    readonly_fields = ['receipt_number', 'created_at', 'updated_at']
    list_editable = ['status']


@admin.register(Refund)
class RefundAdmin(admin.ModelAdmin):
    list_display = ['payment', 'amount', 'reason', 'status', 'processed_by', 'created_at']
    list_filter = ['status']
    search_fields = ['payment__receipt_number', 'payment__student__first_name', 'payment__student__surname', 'reason']
    ordering = ['-created_at']
    date_hierarchy = 'created_at'
    list_editable = ['status']


@admin.register(BankAccount)
class BankAccountAdmin(admin.ModelAdmin):
    list_display = ['name', 'bank_name', 'account_number', 'ifsc_code', 'branch_name', 'is_active', 'created_at']
    list_filter = ['is_active']
    search_fields = ['name', 'bank_name', 'account_number', 'ifsc_code']
    ordering = ['name']
    list_editable = ['is_active']
