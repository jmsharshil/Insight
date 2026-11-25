"""
schofee_finance/admin.py
────────────────────────
Admin registrations for SchoFee Finance models.
Sensitive fields (trace IDs, verification IDs, document paths) are read-only.
"""

from django.contrib import admin
from .models import CourseMapping, FinanceApplication, FinanceDocument, FinanceParticipant


class FinanceParticipantInline(admin.TabularInline):
    model = FinanceParticipant
    extra = 0
    readonly_fields = (
        "schofee_participant_id",
        "role",
        "participant_user_type",
        "full_name",
        "mobile_number",
        "verification_id",
        "is_verified",
        "verified_at",
    )
    can_delete = False


class FinanceDocumentInline(admin.TabularInline):
    model = FinanceDocument
    extra = 0
    readonly_fields = ("owner_type", "document_for", "schofee_path", "uploaded_at")
    can_delete = False


@admin.register(FinanceApplication)
class FinanceApplicationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "admission",
        "status",
        "schofee_loan_app_id",
        "number_of_emis",
        "estimated_emi_amount",
        "last_error_code",
        "created_at",
    )
    list_filter = ("status", "created_at")
    search_fields = (
        "id",
        "admission__id",
        "admission__admission_code",
        "external_student_ref",
        "external_application_ref",
        "schofee_student_id",
        "schofee_loan_app_id",
    )
    readonly_fields = (
        "admission",
        "schofee_student_id",
        "schofee_loan_app_id",
        "schofee_customer_id",
        "schofee_course_id",
        "external_student_ref",
        "external_application_ref",
        "estimated_emi_amount",
        "last_error_code",
        "last_error_message",
        "last_trace_id",
        "created_at",
        "updated_at",
    )
    inlines = [FinanceParticipantInline, FinanceDocumentInline]


@admin.register(FinanceParticipant)
class FinanceParticipantAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "finance_application",
        "role",
        "full_name",
        "mobile_number",
        "is_verified",
        "verified_at",
    )
    list_filter = ("role", "is_verified")
    search_fields = ("full_name", "mobile_number", "schofee_participant_id", "verification_id")
    readonly_fields = (
        "finance_application",
        "schofee_participant_id",
        "role",
        "participant_user_type",
        "verification_id",
        "is_verified",
        "verified_at",
        "created_at",
        "updated_at",
    )


@admin.register(FinanceDocument)
class FinanceDocumentAdmin(admin.ModelAdmin):
    list_display = ("id", "finance_application", "owner_type", "document_for", "uploaded_at")
    list_filter = ("owner_type", "document_for")
    readonly_fields = ("finance_application", "owner_type", "document_for", "schofee_path", "uploaded_at")

    def has_add_permission(self, request):
        return False


@admin.register(CourseMapping)
class CourseMappingAdmin(admin.ModelAdmin):
    list_display = (
        "schofee_course_code",
        "schofee_course_name",
        "local_course_slug",
        "schofee_course_fees",
        "max_emi_months",
        "is_active",
    )
    list_filter = ("is_active", "local_course_slug")
    search_fields = ("schofee_course_code", "schofee_course_name", "schofee_course_id")
