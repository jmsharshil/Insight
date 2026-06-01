from django.urls import path
from .views import (
    FeeStructureListView, FeeStructureDetailView,
    StudentFeeListView, StudentFeeDetailView, StudentFeeByStudentView,
    InstallmentPlanListView, InstallmentPlanCreateView, InstallmentPlanApproveView,
    PaymentListView, PaymentDetailView, PaymentVerifyView,
    RefundListView, RefundCreateView, RefundUpdateView,
    BankAccountListView, BankAccountDetailView,
    FeeReportView,
)

urlpatterns = [
    # ── Fee Structures ─────────────────────────────────────────────────────
    path('fee-structures/', FeeStructureListView.as_view(), name='fee-structure-list'),
    path('fee-structures/<uuid:pk>/', FeeStructureDetailView.as_view(), name='fee-structure-detail'),

    # ── Student Fees ───────────────────────────────────────────────────────
    path('student-fees/', StudentFeeListView.as_view(), name='student-fee-list'),
    path('student-fees/<uuid:pk>/', StudentFeeDetailView.as_view(), name='student-fee-detail'),
    path('fees/student/<uuid:student_id>/', StudentFeeByStudentView.as_view(), name='student-fee-overview'),

    # ── Installments ───────────────────────────────────────────────────────
    path('installments/', InstallmentPlanListView.as_view(), name='installment-list'),
    path('installments/create/', InstallmentPlanCreateView.as_view(), name='installment-create'),
    path('installments/<uuid:pk>/approve/', InstallmentPlanApproveView.as_view(), name='installment-approve'),

    # ── Payments ───────────────────────────────────────────────────────────
    path('payments/', PaymentListView.as_view(), name='payment-list'),
    path('payments/<uuid:pk>/', PaymentDetailView.as_view(), name='payment-detail'),
    path('payments/<uuid:pk>/verify/', PaymentVerifyView.as_view(), name='payment-verify'),

    # ── Refunds ────────────────────────────────────────────────────────────
    path('refunds/', RefundListView.as_view(), name='refund-list'),
    path('refunds/create/', RefundCreateView.as_view(), name='refund-create'),
    path('refunds/<uuid:pk>/', RefundUpdateView.as_view(), name='refund-update'),

    # ── Bank Accounts ──────────────────────────────────────────────────────
    path('bank-accounts/', BankAccountListView.as_view(), name='bank-account-list'),
    path('bank-accounts/<uuid:pk>/', BankAccountDetailView.as_view(), name='bank-account-detail'),

    # ── Reports ────────────────────────────────────────────────────────────
    path('fees/report/', FeeReportView.as_view(), name='fee-report'),
]
