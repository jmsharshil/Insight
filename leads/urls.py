from django.urls import path
from .views import (
    LeadStatusUpdateView, LeadListView, LeadDetailView, LeadReassignView, LeadAssignView,
    LeadTransferRequestListCreateView, LeadTransferRequestReviewView,
    SalesDailyActivityView, SalesActivityPhotoView,
    OdometerReadingListView, OdometerReadingDetailView,
    OdometerReadingApproveView, OdometerReadingRejectView,
)

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
    path("sales/odometer-readings/", OdometerReadingListView.as_view(), name="sales-odometer-readings-list"),
    path("sales/odometer-readings/<uuid:pk>/", OdometerReadingDetailView.as_view(), name="sales-odometer-readings-detail"),
    path("sales/odometer-readings/<uuid:pk>/approve/", OdometerReadingApproveView.as_view(), name="sales-odometer-readings-approve"),
    path("sales/odometer-readings/<uuid:pk>/reject/", OdometerReadingRejectView.as_view(), name="sales-odometer-readings-reject"),
]
