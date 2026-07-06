from types import SimpleNamespace

from django.test import SimpleTestCase

from exams.utils import requires_paper_checking


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
