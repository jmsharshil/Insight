from django.urls import path
from .views import (
    ExamListCreateView, ExamDetailView, QuestionView, QuestionDetailView,
    SeatingView, SeatingDetailView,
    ExamStartView, ExamSubmitView, AutosaveView, ScreenEventView,
    GeoCheckView, AnswerKeyDistributeView, AnswerKeyView,
    MalpracticeView, MalpracticeDetailView, ExamScheduleView,
    SubjectPaperListCreateView, SubjectPaperDetailView,
)

urlpatterns = [
    # Exempt — must come before authenticated routes
    path('answer-key/<uuid:exam_id>/', AnswerKeyView.as_view(), name='answer-key-view'),

    # Exam CRUD
    path('exams/', ExamListCreateView.as_view(), name='exam-list-create'),
    path('exams/<uuid:exam_id>/', ExamDetailView.as_view(), name='exam-detail'),
    path('exams/<uuid:exam_id>/schedule/', ExamScheduleView.as_view(), name='exam-schedule'),

    # Subject Papers (reusable per-subject paper uploads)
    path('subjects/<uuid:subject_id>/papers/', SubjectPaperListCreateView.as_view(), name='subject-papers'),
    path('subjects/<uuid:subject_id>/papers/<uuid:paper_id>/', SubjectPaperDetailView.as_view(), name='subject-paper-detail'),

    # Questions
    path('exams/<uuid:exam_id>/questions/', QuestionView.as_view(), name='exam-questions'),
    path('exams/<uuid:exam_id>/questions/<uuid:question_id>/', QuestionDetailView.as_view(), name='exam-question-detail'),


    # Seating
    path('exams/<uuid:exam_id>/seating/', SeatingView.as_view(), name='exam-seating'),
    path('exams/<uuid:exam_id>/seating/<uuid:seat_id>/', SeatingDetailView.as_view(), name='exam-seating-detail'),

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
    path('exams/<uuid:exam_id>/malpractice/<uuid:report_id>/', MalpracticeDetailView.as_view(), name='exam-malpractice-detail'),
]
