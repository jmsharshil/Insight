from django.urls import path
from .views import (StudentListView,StudentDetailView,StudentSelfProfileView,StudentQRIdentityView,StudentRegenerateIDCardView,StudentStatusUpdateView,StudentBatchAllocateView,StudentDocumentUploadView,StudentInventoryView,)
 
urlpatterns = [
    path('students/', StudentListView.as_view(),name='student-list'),
    path('students/<uuid:student_id>/',StudentDetailView.as_view(),name='student-detail'),
    path('students/<uuid:student_id>/profile/',StudentSelfProfileView.as_view(),name='student-profile'),
    path('students/<uuid:student_id>/qr-id/',StudentQRIdentityView.as_view(),name='student-qr-id'),
    path('students/<uuid:student_id>/regenerate-id-card/',StudentRegenerateIDCardView.as_view(),name='student-regenerate-id-card'),
    path('students/<uuid:student_id>/status/',StudentStatusUpdateView.as_view(),name='student-status'),
    path('students/<uuid:student_id>/batch/',StudentBatchAllocateView.as_view(),name='student-batch'),
    path('students/<uuid:student_id>/documents/', StudentDocumentUploadView.as_view(),name='student-documents'),
    path('students/<uuid:student_id>/inventory/', StudentInventoryView.as_view(),name='student-inventory'),
]