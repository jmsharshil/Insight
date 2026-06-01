from django.urls import path
from .views import (
    ExamListCreateView, ExamDetailView, QuestionView, SeatingView,
    ExamStartView, ExamSubmitView, AutosaveView, ScreenEventView,
    GeoCheckView, AnswerKeyDistributeView, AnswerKeyView, MalpracticeView,
)

urlpatterns = [
    # Exempt — must come before authenticated routes
    path('answer-key/<uuid:exam_id>/', AnswerKeyView.as_view(), name='answer-key-view'),

    # Exam CRUD
    path('exams/', ExamListCreateView.as_view(), name='exam-list-create'),
    path('exams/<uuid:exam_id>/', ExamDetailView.as_view(), name='exam-detail'),

    # Questions
    path('exams/<uuid:exam_id>/questions/', QuestionView.as_view(), name='exam-questions'),

    # Seating
    path('exams/<uuid:exam_id>/seating/', SeatingView.as_view(), name='exam-seating'),

    # Online exam flow
    path('exams/<uuid:exam_id>/start/', ExamStartView.as_view(), name='exam-start'),
    path('exams/<uuid:exam_id>/submit/', ExamSubmitView.as_view(), name='exam-submit'),
    path('exams/<uuid:exam_id>/sessions/<uuid:session_id>/autosave/', AutosaveView.as_view(), name='exam-autosave'),
    path('exams/<uuid:exam_id>/sessions/<uuid:session_id>/screen-event/', ScreenEventView.as_view(), name='exam-screen-event'),
    # v2 NEW: periodic geo-check (FRD §4.6.1)
    path('exams/<uuid:exam_id>/sessions/<uuid:session_id>/geo-check/', GeoCheckView.as_view(), name='exam-geo-check'),

    # Answer key & malpractice
    path('exams/<uuid:exam_id>/answer-key/distribute/', AnswerKeyDistributeView.as_view(), name='exam-answer-key-dist'),
    path('exams/<uuid:exam_id>/malpractice/', MalpracticeView.as_view(), name='exam-malpractice'),
]
