from django.urls import path
from .views import (
    LeaveListCreateView, LeaveDetailView, LeaveApproveView, LeaveRejectView,
    LeavePolicyView, LeavePolicyDetailView, LeaveBalanceView, LeaveBalanceUserView,
    LateEntryListCreateView, LateEntryDetailView,
    PublicHolidayListCreateView, PublicHolidayDetailView,
    StudentLeaveListCreateView, StudentLeaveDetailView,
    StudentLeaveApproveView, StudentLeaveRejectView,
)

urlpatterns = [
    path('leave/', LeaveListCreateView.as_view(), name='leave-list-create'),
    path('leave/policy/', LeavePolicyView.as_view(), name='leave-policy'),
    path('leave/policy/<uuid:policy_id>/', LeavePolicyDetailView.as_view(), name='leave-policy-detail'),
    path('leave/balance/', LeaveBalanceView.as_view(), name='leave-balance'),
    path('leave/balance/<uuid:user_id>/', LeaveBalanceUserView.as_view(), name='leave-balance-user'),
    path('leave/late-entries/', LateEntryListCreateView.as_view(), name='late-entries'),
    path('leave/late-entries/<uuid:entry_id>/', LateEntryDetailView.as_view(), name='late-entry-detail'),
    path('leave/public-holidays/', PublicHolidayListCreateView.as_view(), name='public-holidays'),
    path('leave/public-holidays/<uuid:holiday_id>/', PublicHolidayDetailView.as_view(), name='public-holiday-detail'),
    path('leave/<uuid:leave_id>/', LeaveDetailView.as_view(), name='leave-detail'),
    path('leave/<uuid:leave_id>/approve/', LeaveApproveView.as_view(), name='leave-approve'),
    path('leave/<uuid:leave_id>/reject/', LeaveRejectView.as_view(), name='leave-reject'),

    # ── Student Leave ────────────────────────────────────────────────────────
    path('leave/student/', StudentLeaveListCreateView.as_view(), name='student-leave-list-create'),
    path('leave/student/<uuid:leave_id>/', StudentLeaveDetailView.as_view(), name='student-leave-detail'),
    path('leave/student/<uuid:leave_id>/approve/', StudentLeaveApproveView.as_view(), name='student-leave-approve'),
    path('leave/student/<uuid:leave_id>/reject/', StudentLeaveRejectView.as_view(), name='student-leave-reject'),
]
