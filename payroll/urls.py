from django.urls import path
from .views import (
    PayrollListCreateView, PayrollDetailView, PayrollPayslipsView,
    PayrollApproveView, PayrollDisburseView, FacultyPayslipsView,
    LatePolicyView, LatePolicyDetailView, PayslipAdjustView, FacultySalaryPreviewView,
    ExtraHoursApprovalListView, ExtraHoursApprovalUpdateView,
    MyPayrollView,
)

urlpatterns = [
    path('payroll/my/', MyPayrollView.as_view(), name='payroll-my'),
    path('payroll/', PayrollListCreateView.as_view(), name='payroll-list-create'),
    path('payroll/<uuid:payroll_id>/', PayrollDetailView.as_view(), name='payroll-detail'),
    path('payroll/<uuid:payroll_id>/payslips/', PayrollPayslipsView.as_view(), name='payroll-payslips'),
    path('payroll/<uuid:payroll_id>/payslips/<uuid:slip_id>/', PayslipAdjustView.as_view(), name='payslip-adjust'),
    path('payroll/<uuid:payroll_id>/approve/', PayrollApproveView.as_view(), name='payroll-approve'),
    path('payroll/<uuid:payroll_id>/disburse/', PayrollDisburseView.as_view(), name='payroll-disburse'),
    path('payroll/late-policy/', LatePolicyView.as_view(), name='payroll-late-policy'),
    path('payroll/late-policy/<uuid:policy_id>/', LatePolicyDetailView.as_view(), name='payroll-late-policy-detail'),
    path('payroll/extra-hours/', ExtraHoursApprovalListView.as_view(), name='payroll-extra-hours-list'),
    path('payroll/extra-hours/<uuid:approval_id>/', ExtraHoursApprovalUpdateView.as_view(), name='payroll-extra-hours-update'),
    path('faculty/<uuid:faculty_id>/payslips/', FacultyPayslipsView.as_view(), name='faculty-payslips'),
    path('faculty/<uuid:faculty_id>/salary-preview/', FacultySalaryPreviewView.as_view(), name='faculty-salary-preview'),
]

