from django.urls import path
from .views import (
    CourseListView, CourseDetailView,
    SubjectListView, SubjectDetailView,
    BatchListView, BatchDetailView,
    BatchAssignStudentsView, BatchRemoveStudentView,
    BatchAssignFacultyView, BatchRemoveFacultyView,
    ClassroomListView, ClassroomDetailView,
    TimetableListView, TimetableDetailView, TimetableDuplicateSlotView,
    TimetableConfirmView,
    FacultyTimetableView, StudentTimetableView,
    CourseLevelListView, CourseLevelDetailView,
    ChapterListView, ChapterDetailView,
    AcademicDropdownsView, TimetablePublishView
)

urlpatterns = [
    # ── Dropdowns ───────────────────────────────────────────────────────────
    path('batches/dropdowns/', AcademicDropdownsView.as_view(), name='academic-dropdowns'),

    # ── Courses ─────────────────────────────────────────────────────────────
    path('courses/', CourseListView.as_view(), name='course-list'),
    path('courses/<uuid:pk>/', CourseDetailView.as_view(), name='course-detail'),
    path('courses/<uuid:course_id>/levels/', CourseLevelListView.as_view(), name='course-level-list'),
    path('courses/<uuid:course_id>/levels/<uuid:level_id>/', CourseLevelDetailView.as_view(), name='course-level-detail'),

    # ── Subjects ────────────────────────────────────────────────────────────
    path('subjects/', SubjectListView.as_view(), name='subject-list'),
    path('subjects/<uuid:pk>/', SubjectDetailView.as_view(), name='subject-detail'),
    path('subjects/<uuid:subject_id>/chapters/', ChapterListView.as_view(), name='chapter-list'),
    path('subjects/<uuid:subject_id>/chapters/<uuid:chapter_id>/', ChapterDetailView.as_view(), name='chapter-detail'),

    # ── Batches ─────────────────────────────────────────────────────────────
    path('batches/', BatchListView.as_view(), name='batch-list'),
    path('batches/<uuid:pk>/', BatchDetailView.as_view(), name='batch-detail'),
    path('batches/<uuid:pk>/assign-students/', BatchAssignStudentsView.as_view(), name='batch-assign-students'),
    path('batches/<uuid:pk>/remove-student/<uuid:student_id>/', BatchRemoveStudentView.as_view(), name='batch-remove-student'),
    path('batches/<uuid:pk>/assign-faculty/', BatchAssignFacultyView.as_view(), name='batch-assign-faculty'),
    path('batches/<uuid:pk>/remove-faculty/<uuid:faculty_id>/', BatchRemoveFacultyView.as_view(), name='batch-remove-faculty'),

    # ── Classrooms ──────────────────────────────────────────────────────────
    path('classrooms/', ClassroomListView.as_view(), name='classroom-list'),
    path('classrooms/<uuid:pk>/', ClassroomDetailView.as_view(), name='classroom-detail'),

    # ── Timetable ───────────────────────────────────────────────────────────
    path('timetable/', TimetableListView.as_view(), name='timetable-list'),
    path('timetable/confirm/', TimetableConfirmView.as_view(), name='timetable-confirm'),
    path('timetable/<uuid:pk>/', TimetableDetailView.as_view(), name='timetable-detail'),
    path('timetable/faculty/<uuid:faculty_id>/', FacultyTimetableView.as_view(), name='faculty-timetable'),
    path('timetable/student/<uuid:student_id>/', StudentTimetableView.as_view(), name='student-timetable'),
    path('timetable/<uuid:pk>/duplicate/', TimetableDuplicateSlotView.as_view(), name='timetable-duplicate-slot'),
    path('timetable/publish/', TimetablePublishView.as_view(), name='timetable-publish'),
]
