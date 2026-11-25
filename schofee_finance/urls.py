"""
schofee_finance/urls.py
───────────────────────
URL routing for SchoFee B2B Education Loan endpoints.
"""

from django.urls import path
from .views import (
    FinanceApplicationCreateView,
    FinanceApplicationDetailView,
    FinanceCoursesListView,
    FinanceParticipantOTPSendView,
    FinanceParticipantOTPVerifyView,
)

app_name = "schofee_finance"

urlpatterns = [
    path("applications/", FinanceApplicationCreateView.as_view(), name="application-create"),
    path("applications/<int:pk>/", FinanceApplicationDetailView.as_view(), name="application-detail"),
    path(
        "applications/<int:pk>/participants/<str:participant_id>/otp/send/",
        FinanceParticipantOTPSendView.as_view(),
        name="participant-otp-send",
    ),
    path(
        "applications/<int:pk>/participants/<str:participant_id>/otp/verify/",
        FinanceParticipantOTPVerifyView.as_view(),
        name="participant-otp-verify",
    ),
    path("courses/", FinanceCoursesListView.as_view(), name="courses-list"),
]
