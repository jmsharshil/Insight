from types import SimpleNamespace

from django.test import SimpleTestCase, override_settings

from exams.utils import build_absolute_url, requires_paper_checking


class PaperCheckerAssignmentRuleTests(SimpleTestCase):
    def test_online_mcq_exam_does_not_require_paper_checking(self):
        exam = SimpleNamespace(exam_mode='online', exam_type='mcq')

        self.assertFalse(requires_paper_checking(exam))

    def test_online_subjective_exam_requires_paper_checking(self):
        exam = SimpleNamespace(exam_mode='online', exam_type='subjective')

        self.assertTrue(requires_paper_checking(exam))

    def test_online_exam_with_subjective_questions_requires_paper_checking(self):
        exam = SimpleNamespace(exam_mode='online', exam_type='mcq')

        self.assertTrue(requires_paper_checking(exam, has_subjective_questions=True))

    def test_offline_exam_requires_paper_checking(self):
        exam = SimpleNamespace(exam_mode='offline', exam_type='mcq')

        self.assertTrue(requires_paper_checking(exam))


class AnswerKeyUrlTests(SimpleTestCase):
    @override_settings(BASE_URL='https://example.com')
    def test_build_absolute_url_uses_configured_backend_base_url(self):
        self.assertEqual(
            build_absolute_url('/api/v1/answer-key/123/?token=abc'),
            'https://example.com/api/v1/answer-key/123/?token=abc',
        )

    @override_settings(BASE_URL='http://localhost:8000')
    def test_build_absolute_url_replaces_localhost_for_local_testing(self):
        self.assertEqual(
            build_absolute_url('/api/v1/answer-key/123/?token=abc'),
            'http://127.0.0.1:8000/api/v1/answer-key/123/?token=abc',
        )
