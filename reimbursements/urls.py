from django.urls import path
from .views import (
    ReimbursementListCreateAPIView,
    ReimbursementDetailAPIView,
    ReimbursementApproveAPIView,
    ReimbursementRejectAPIView,
    ReimbursementSummaryAPIView,
)

urlpatterns = [
    path('', ReimbursementListCreateAPIView.as_view(), name='reimbursement-list-create'),
    path('summary/', ReimbursementSummaryAPIView.as_view(), name='reimbursement-summary'),
    path('<uuid:pk>/', ReimbursementDetailAPIView.as_view(), name='reimbursement-detail'),
    path('<uuid:pk>/approve/', ReimbursementApproveAPIView.as_view(), name='reimbursement-approve'),
    path('<uuid:pk>/reject/', ReimbursementRejectAPIView.as_view(), name='reimbursement-reject'),
]
