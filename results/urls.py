from django.urls import path
from .views import (
    PaperView, PaperMarksView, PaperRecheckView,
    CheckerStatusView, CheckerPortalSubmitView,
    PublishResultView, ResultView, ResultDeleteView,
    StudentRecheckRequestView, RecheckRequestListView, RecheckRequestActionView,
    MarkAbsentView, MarkAllAbsentView, BulkRecheckRequestView, PaperCheckerQueryView,
    SubjectWiseResultView, FacultyWiseResultView, BatchWiseResultView, ResultAnalyticsView,
    ResultExportView,
)

urlpatterns = [
    # Exempt endpoint
    path('checker-portal/submit/', CheckerPortalSubmitView.as_view(), name='checker-portal-submit'),
    
    path('exams/<uuid:exam_id>/papers/', PaperView.as_view(), name='paper-list'),
    path('exams/<uuid:exam_id>/papers/<uuid:marksheet_id>/marks/', PaperMarksView.as_view(), name='paper-marks'),
    path('exams/<uuid:exam_id>/papers/<uuid:marksheet_id>/recheck/', PaperRecheckView.as_view(), name='paper-recheck'),
    path('exams/<uuid:exam_id>/papers/<uuid:marksheet_id>/mark-absent/', MarkAbsentView.as_view(), name='mark-absent'),
    path('exams/<uuid:exam_id>/mark-absent-all/', MarkAllAbsentView.as_view(), name='mark-absent-all'),
    path('exams/<uuid:exam_id>/checker-status/', CheckerStatusView.as_view(), name='checker-status'),
    path('exams/<uuid:exam_id>/results/publish/', PublishResultView.as_view(), name='publish-result'),
    path('exams/<uuid:exam_id>/results/', ResultView.as_view(), name='exam-results'),
    path('exams/<uuid:exam_id>/results/<uuid:result_id>/', ResultDeleteView.as_view(), name='result-delete'),
    
    # v2 NEW: FRD §4.6.2 Recheck Requests
    path('exams/<uuid:exam_id>/results/recheck-request/', StudentRecheckRequestView.as_view(), name='student-recheck-request'),
    path('exams/<uuid:exam_id>/results/recheck-request/bulk/', BulkRecheckRequestView.as_view(), name='bulk-recheck-request'),
    path('exams/<uuid:exam_id>/recheck-requests/', RecheckRequestListView.as_view(), name='recheck-request-list'),
    path('exams/<uuid:exam_id>/recheck-requests/<uuid:request_id>/', RecheckRequestActionView.as_view(), name='recheck-request-action'),
    
    # NEW: Paper checker query option
    path('exams/<uuid:exam_id>/papers/<uuid:marksheet_id>/query/', PaperCheckerQueryView.as_view(), name='paper-checker-query'),
    path('exams/<uuid:exam_id>/queries/<uuid:query_id>/resolve/', PaperCheckerQueryView.as_view(), name='query-resolve'),
    
    # Subject-wise, Faculty-wise, Batch-wise & Summary APIs (on-the-fly via PublishedResult + Exam relations; no extra models)
    path('results/subject-wise/', SubjectWiseResultView.as_view(), name='subject-wise-results'),
    path('results/faculty-wise/', FacultyWiseResultView.as_view(), name='faculty-wise-results'),
    path('results/batch-wise/', BatchWiseResultView.as_view(), name='batch-wise-results'),
    path('results/summary/', ResultAnalyticsView.as_view(), name='result-summary'),
    path('results/analytics/', ResultAnalyticsView.as_view(), name='result-analytics'),
    
    # NEW: Export API for results/aggregates (CSV download)
    path('results/export/', ResultExportView.as_view(), name='results-export'),
]

