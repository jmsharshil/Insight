from django.contrib import admin
from .models import Reimbursement


@admin.register(Reimbursement)
class ReimbursementAdmin(admin.ModelAdmin):
    list_display = ('title', 'user', 'branch', 'amount', 'status', 'expense_date', 'is_paid', 'created_at')
    list_filter = ('status', 'is_paid', 'branch', 'expense_date')
    search_fields = ('title', 'description', 'user__name', 'user__email')
    readonly_fields = ('created_at', 'updated_at', 'approved_at', 'rejected_at')
