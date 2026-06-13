from django.urls import path
from .views import LeadStatusUpdateView, LeadListView, LeadDetailView, LeadReassignView, LeadAssignView

urlpatterns = [
    path("leads/", LeadListView.as_view(), name="lead-list"),
    path("leads/<int:lead_id>/", LeadDetailView.as_view(), name="lead-detail"),
    path("leads/<int:lead_id>/status/", LeadStatusUpdateView.as_view(), name="lead-status-update"),
    path("leads/<int:lead_id>/assign/", LeadAssignView.as_view(), name="lead-assign"),
    path("leads/<int:lead_id>/reassign/", LeadReassignView.as_view(), name="lead-reassign"),
]
