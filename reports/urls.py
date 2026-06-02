"""reports/urls.py — URL routing for reporting & analytics module."""
from django.urls import path
from . import views

urlpatterns = [
    path('reports/dashboard/', views.DashboardView.as_view(), name='report-dashboard'),
    path('reports/students/', views.StudentReportView.as_view(), name='report-students'),
    path('reports/attendance/', views.AttendanceReportView.as_view(), name='report-attendance'),
    path('reports/fees/', views.FeeReportView.as_view(), name='report-fees'),
    path('reports/timetable/', views.TimetableReportView.as_view(), name='report-timetable'),
    path('reports/exams/', views.ExamReportView.as_view(), name='report-exams'),
    path('reports/payroll/', views.PayrollReportView.as_view(), name='report-payroll'),
    path('reports/leads/', views.LeadReportView.as_view(), name='report-leads'),
    path('reports/leaves/', views.LeaveReportView.as_view(), name='report-leaves'),
    path('reports/export/<str:report_type>/', views.ExportView.as_view(), name='report-export'),
]
