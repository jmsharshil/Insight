from django.urls import path
from .views import (
    PayrollListCreateView, PayrollDetailView, PayrollPayslipsView,
    PayrollApproveView, PayrollDisburseView, FacultyPayslipsView, LatePolicyView,
)

urlpatterns = [
    path('payroll/', PayrollListCreateView.as_view(), name='payroll-list-create'),
    path('payroll/<uuid:payroll_id>/', PayrollDetailView.as_view(), name='payroll-detail'),
    path('payroll/<uuid:payroll_id>/payslips/', PayrollPayslipsView.as_view(), name='payroll-payslips'),
    path('payroll/<uuid:payroll_id>/approve/', PayrollApproveView.as_view(), name='payroll-approve'),
    path('payroll/<uuid:payroll_id>/disburse/', PayrollDisburseView.as_view(), name='payroll-disburse'),
    path('payroll/late-policy/', LatePolicyView.as_view(), name='payroll-late-policy'),
    path('faculty/<uuid:faculty_id>/payslips/', FacultyPayslipsView.as_view(), name='faculty-payslips'),
]
