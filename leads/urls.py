from django.urls import path
from .views import (LeadStatusUpdateView, LeadListView, LeadDetailView, LeadReassignView, LeadAssignView,
                    LeadTransferRequestListCreateView, LeadTransferRequestReviewView,
                    SalesDailyActivityView, SalesActivityPhotoView)

urlpatterns = [
    path("leads/", LeadListView.as_view(), name="lead-list"),
    path("leads/<int:lead_id>/", LeadDetailView.as_view(), name="lead-detail"),
    path("leads/<int:lead_id>/status/", LeadStatusUpdateView.as_view(), name="lead-status-update"),
    path("leads/<int:lead_id>/assign/", LeadAssignView.as_view(), name="lead-assign"),
    path("leads/<int:lead_id>/reassign/", LeadReassignView.as_view(), name="lead-reassign"),
    path("leads/transfer-requests/", LeadTransferRequestListCreateView.as_view(), name="lead-transfer-requests"),
    path("leads/transfer-requests/<int:pk>/review/", LeadTransferRequestReviewView.as_view(), name="lead-transfer-request-review"),
    path("sales/activities/", SalesDailyActivityView.as_view(), name="sales-daily-activities"),
    path("sales/activities/<uuid:activity_id>/photos/", SalesActivityPhotoView.as_view(), name="sales-activity-photos"),
]
