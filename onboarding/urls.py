from django.urls import path
from .views import AdmissionListView, AdmissionDetailView, AdmissionStatusUpdateView,AdmissionApproveView,AdmissionRejectView,AdmissionDocumentUploadView,AdmissionUpdateView,AdmissionPaymentSubmitView, RazorpayWebhookView, AdmissionPaymentSetupView

urlpatterns = [
    path('admissions/', AdmissionListView.as_view()),
    path('admissions/razorpay-webhook/', RazorpayWebhookView.as_view(), name='razorpay-webhook'),
    path('admissions/<str:admission_id>/', AdmissionDetailView.as_view()),
    path('admissions/<str:admission_id>/status/', AdmissionStatusUpdateView.as_view()),
    path('admissions/<str:admission_id>/approve/',AdmissionApproveView.as_view(),name='admission-approve'),
    path('admissions/<str:admission_id>/reject/',AdmissionRejectView.as_view(),name='admission-reject'),
    path('admissions/<str:admission_id>/documents/',AdmissionDocumentUploadView.as_view(),  name='admission-documents'),
    path('admissions/<str:admission_id>/payment/',AdmissionPaymentSubmitView.as_view(),  name='admission-payment'),
    path('admissions/<str:admission_id>/setup/',  AdmissionPaymentSetupView.as_view(),   name='admission-payment-setup'),

]