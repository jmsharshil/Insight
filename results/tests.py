import os
import django
from django.test import SimpleTestCase
from django.utils import timezone

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'insight.settings')
django.setup()

from results.views import build_exam_export_workbook


class ExamExportWorkbookTests(SimpleTestCase):
    def test_marks_cells_are_styled_without_text_prefixes(self):
        rows = [
            ("Alice", "R1", 25, 100, 25.0, 1, True, timezone.now(), "Math"),
            ("Bob", "R2", 70, 100, 70.0, 2, True, timezone.now(), "Math"),
        ]

        workbook = build_exam_export_workbook(rows)
        sheet = workbook.active

        self.assertEqual(sheet["C2"].value, 25)
        self.assertEqual(sheet["C3"].value, 70)
        self.assertEqual(sheet["C2"].fill.patternType, "solid")
        self.assertEqual(sheet["C3"].fill.patternType, "solid")
        self.assertNotEqual(sheet["C2"].fill.fgColor.rgb, None)
        self.assertNotEqual(sheet["C3"].fill.fgColor.rgb, None)
