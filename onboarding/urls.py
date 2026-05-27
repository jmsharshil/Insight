from django.urls import path
from .views import AdmissionListView, AdmissionDetailView, AdmissionStatusUpdateView

urlpatterns = [
    path('admissions/', AdmissionListView.as_view()),
    path('admissions/<int:admission_id>/', AdmissionDetailView.as_view()),
    path('admissions/<int:admission_id>/status/', AdmissionStatusUpdateView.as_view()),
]