from django.urls import path
from .views import (
    FeeStructureListView, FeeStructureDetailView,
    StudentFeeListView, StudentFeeDetailView, StudentFeeByStudentView,
    InstallmentPlanListView, InstallmentPlanCreateView, InstallmentPlanApproveView,
    PaymentListView, PaymentDetailView, PaymentVerifyView,
    RefundListView, RefundCreateView, RefundUpdateView,
    BankAccountListView, BankAccountDetailView,
    FeeReportView,
    StudentFeeSummaryView,
    MyFeesAPIView,
    # Razorpay
    RazorpayGeneratePaymentLinkView,
    RazorpayDirectPaymentLinkView,
    RazorpayFetchPaymentLinkView,
    RazorpayCancelPaymentLinkView,
    RazorpayFetchPaymentView,
    RazorpayRefundView,
    RazorpayWebhookView,
    RazorpayWebhookTestView,
)

urlpatterns = [
    # ── Fee Structures ─────────────────────────────────────────────────────
    path('fee-structures/', FeeStructureListView.as_view(), name='fee-structure-list'),
    path('fee-structures/<uuid:pk>/', FeeStructureDetailView.as_view(), name='fee-structure-detail'),

    # ── Student Fees ───────────────────────────────────────────────────────
    path('student-fees/', StudentFeeListView.as_view(), name='student-fee-list'),
    path('student-fees/summary/', StudentFeeSummaryView.as_view(), name='student-fee-summary'),
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
    
    # ── Token-based My Fees API ────────────────────────────────────────────
    path('fees/my-fees/', MyFeesAPIView.as_view(), name='my-fees'),

    # ── Razorpay ───────────────────────────────────────────────────────────
    path('razorpay/webhook/',                            RazorpayWebhookView.as_view(),            name='razorpay-webhook'),
    path('razorpay/webhook/test/',                       RazorpayWebhookTestView.as_view(),        name='razorpay-webhook-test'),
    path('razorpay/generate-link/',                      RazorpayGeneratePaymentLinkView.as_view(), name='razorpay-generate-link'),
    path('razorpay/generate-direct-link/',               RazorpayDirectPaymentLinkView.as_view(),   name='razorpay-generate-direct-link'),
    path('razorpay/payment-link/<str:link_id>/',         RazorpayFetchPaymentLinkView.as_view(),    name='razorpay-fetch-link'),
    path('razorpay/cancel-link/<str:link_id>/',          RazorpayCancelPaymentLinkView.as_view(),   name='razorpay-cancel-link'),
    path('razorpay/payment/<str:razorpay_payment_id>/',  RazorpayFetchPaymentView.as_view(),        name='razorpay-fetch-payment'),
    path('razorpay/refund/',                             RazorpayRefundView.as_view(),              name='razorpay-refund'),
]
