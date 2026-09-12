from django.urls import path
from .views import (
    LeadStatusUpdateView, LeadListView, LeadDetailView, LeadReassignView, LeadAssignView,
    LeadTransferRequestListCreateView, LeadTransferRequestReviewView,
    SalesDailyPlanView, SalesDailyPlanDetailView, TriggerSalesRemindersView,
    SalesDailyActivityView, SalesActivityPhotoView,
    OdometerReadingListView, OdometerReadingDetailView,
    OdometerReadingApproveView, OdometerReadingRejectView,
    MonthlyOdometerApproveView, MonthlyOdometerRejectView,
)

urlpatterns = [
    path("leads/", LeadListView.as_view(), name="lead-list"),
    path("leads/<int:lead_id>/", LeadDetailView.as_view(), name="lead-detail"),
    path("leads/<int:lead_id>/status/", LeadStatusUpdateView.as_view(), name="lead-status-update"),
    path("leads/<int:lead_id>/assign/", LeadAssignView.as_view(), name="lead-assign"),
    path("leads/<int:lead_id>/reassign/", LeadReassignView.as_view(), name="lead-reassign"),
    path("leads/transfer-requests/", LeadTransferRequestListCreateView.as_view(), name="lead-transfer-requests"),
    path("leads/transfer-requests/<int:pk>/review/", LeadTransferRequestReviewView.as_view(), name="lead-transfer-request-review"),
    path("sales/plans/", SalesDailyPlanView.as_view(), name="sales-daily-plans"),
    path("sales/plans/send-reminders/", TriggerSalesRemindersView.as_view(), name="sales-plans-send-reminders"),
    path("sales/plans/<uuid:pk>/", SalesDailyPlanDetailView.as_view(), name="sales-daily-plans-detail"),
    path("sales/activities/", SalesDailyActivityView.as_view(), name="sales-daily-activities"),
    path("sales/activities/<uuid:activity_id>/photos/", SalesActivityPhotoView.as_view(), name="sales-activity-photos"),
    path("sales/odometer-readings/", OdometerReadingListView.as_view(), name="sales-odometer-readings-list"),
    path("sales/odometer-readings/<uuid:pk>/", OdometerReadingDetailView.as_view(), name="sales-odometer-readings-detail"),
    path("sales/odometer-readings/<uuid:pk>/approve/", OdometerReadingApproveView.as_view(), name="sales-odometer-readings-approve"),
    path("sales/odometer-readings/<uuid:pk>/reject/", OdometerReadingRejectView.as_view(), name="sales-odometer-readings-reject"),
    # Monthly approval endpoints (new - aggregates daily readings per user/month)
    path("sales/odometer/monthly/approve/", MonthlyOdometerApproveView.as_view(), name="sales-odometer-monthly-approve"),
    path("sales/odometer/monthly/reject/", MonthlyOdometerRejectView.as_view(), name="sales-odometer-monthly-reject"),
]
