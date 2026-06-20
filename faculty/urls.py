from django.urls import path
from .views import (
    FacultyListCreateView, FacultyDetailView, FacultyQRIDView,
    FacultyQRCheckinView, SubjectHourlyRateView, SubjectRateDetailView,
    SessionListCreateView, SessionDetailView, SessionSummaryView,
    FacultySessionsView, FacultyExtraHoursView,
)

urlpatterns = [
    path('faculty/', FacultyListCreateView.as_view(), name='faculty-list-create'),
    path('faculty/qr-checkin/', FacultyQRCheckinView.as_view(), name='faculty-qr-checkin'),
    path('faculty/extra-hours/', FacultyExtraHoursView.as_view(), name='faculty-extra-hours'),
    path('faculty/sessions/', SessionListCreateView.as_view(), name='session-list-create'),
    path('faculty/sessions/summary/', SessionSummaryView.as_view(), name='session-summary'),
    path('faculty/sessions/<uuid:session_id>/', SessionDetailView.as_view(), name='session-detail'),
    path('faculty/<uuid:faculty_id>/', FacultyDetailView.as_view(), name='faculty-detail'),
    path('faculty/<uuid:faculty_id>/qr-id/', FacultyQRIDView.as_view(), name='faculty-qr-id'),
    path('faculty/<uuid:faculty_id>/subject-rates/', SubjectHourlyRateView.as_view(), name='faculty-subject-rates'),
    path('faculty/<uuid:faculty_id>/subject-rates/<uuid:rate_id>/', SubjectRateDetailView.as_view(), name='faculty-subject-rate-detail'),
    path('faculty/<uuid:faculty_id>/sessions/', FacultySessionsView.as_view(), name='faculty-sessions'),
]

