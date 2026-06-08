from django.urls import path
from .views import AdmissionListView, AdmissionDetailView, AdmissionStatusUpdateView,AdmissionApproveView,AdmissionRejectView,AdmissionDocumentUploadView,AdmissionUpdateView,AdmissionPaymentSubmitView

urlpatterns = [
    path('admissions/', AdmissionListView.as_view()),
    path('admissions/<int:admission_id>/', AdmissionDetailView.as_view()),
    path('admissions/<int:admission_id>/status/', AdmissionStatusUpdateView.as_view()),
    path('admissions/<int:admission_id>/approve/',AdmissionApproveView.as_view(),name='admission-approve'),
    path('admissions/<int:admission_id>/reject/',AdmissionRejectView.as_view(),name='admission-reject'),
    path('admissions/<int:admission_id>/documents/',AdmissionDocumentUploadView.as_view(),  name='admission-documents'),
    path('admissions/<int:admission_id>/payment/',AdmissionPaymentSubmitView.as_view(),  name='admission-payment'),

]