from django.urls import path

from .views import (BranchListCreateAPIView,BranchDetailAPIView,BranchSummaryAPIView,)

urlpatterns = [
    path("branches/",BranchListCreateAPIView.as_view(),name="branch-list-create"),
    path("branches/<uuid:pk>/",BranchDetailAPIView.as_view(),name="branch-detail"),
    path("branches/<uuid:pk>/summary/",BranchSummaryAPIView.as_view(),name="branch-summary"),
]