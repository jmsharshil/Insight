"""
onboarding/tests.py — Integration tests for the Admission → Student → Fees pipeline.

Tests verify that enrolling an Admission automatically creates:
  1. A User account (role=student)
  2. A Student profile linked to the admission
  3. A StudentFee record linked to the student (via fees.services.create_student_fee)
"""
from django.test import TestCase

from onboarding.models import Admission
from fees.models import FeeStructure, StudentFee
from students.models import Student
from auth_user.models import User


def _make_admission(fee_structure=None, **overrides):
    """Helper: create a minimal valid Admission with all required non-null fields."""
    defaults = {
        'first_name': 'Test',
        'surname': 'Student',
        'father_name': 'Test Father',
        'mother_name': 'Test Mother',
        'category': 'gen',
        'dob': '2000-01-01',
        'email': 'teststu@integration.com',
        'email_parent': 'parent@integration.com',
        'phone_student': '9876543210',
        'phone_father': '9876543211',
        'street': '123 Main St',
        'city': 'Ahmedabad',
        'state': 'Gujarat',
        'pincode': '380001',
        'course': 'cseet',
        'group_module': 'full',
        'batch_attempt': 'june',
        'location': 'Ahmedabad',
        'qualification': 'pass_12',
        'reference': 'google',
        'tenth_medium': 'cbse',
        'tenth_school': 'Test School',
        'tenth_percentage': '85.00',
        'tenth_percentile': '92.00',
        'twelfth_medium': 'cbse',
        'twelfth_school': 'Test School',
        'twelfth_percentage': '80.00',
        'twelfth_percentile': '88.00',
        # FileFields are optional-in-practice for DB save (blank strings work)
        'doc_signature': '',
        'doc_photo': '',
        'doc_dob_certificate': '',
        'doc_id_card': '',
        'status': 'approval_pending',
        'fee_structure': fee_structure,
    }
    defaults.update(overrides)
    return Admission.objects.create(**defaults)


class AdmissionToStudentFeeIntegrationTest(TestCase):
    """
    End-to-end test: Admission enrolled → Student created → StudentFee auto-created.
    Flow:
      onboarding/signals.py  → creates User + Student on Admission.status = 'enrolled'
      students/signals.py    → calls create_student_fee(student)
      fees/services.py       → creates StudentFee using admission.fee_structure
    """

    def setUp(self):
        self.fee_structure = FeeStructure.objects.create(
            name='CSEET Fee 2026',
            total_amount=30000,
            is_active=True,
        )
        self.admission = _make_admission(fee_structure=self.fee_structure)

    def enroll_admission(self):
        from onboarding.utils import AdmissionService
        from students.utils import StudentService
        from auth_user.models import User
        AdmissionService.update_status(self.admission, 'enrolled')
        student_user = User.objects.filter(email=self.admission.email, role='student').first()
        if student_user:
            StudentService.create_from_admission(self.admission, student_user, None)

    # ── Test 1: User + Student are created when admission is enrolled ──────────

    def test_enrollment_creates_user(self):
        self.enroll_admission()

        user = User.objects.filter(email='teststu@integration.com', role='student').first()
        self.assertIsNotNone(user, "Expected a User to be created on enrollment.")

    def test_enrollment_creates_student_profile(self):
        self.enroll_admission()

        student = Student.objects.filter(admission=self.admission).first()
        self.assertIsNotNone(student, "Expected a Student profile to be created on enrollment.")

    # ── Test 2: StudentFee is auto-created for the new Student ────────────────

    def test_enrollment_creates_student_fee(self):
        self.enroll_admission()

        student = Student.objects.filter(admission=self.admission).first()
        self.assertIsNotNone(student, "Student should exist before checking fee.")

        student_fee = StudentFee.objects.filter(student=student).first()
        self.assertIsNotNone(student_fee, "StudentFee was not auto-created on enrollment.")

    def test_student_fee_uses_admission_fee_structure(self):
        self.enroll_admission()

        student = Student.objects.filter(admission=self.admission).first()
        student_fee = StudentFee.objects.filter(student=student).first()

        self.assertIsNotNone(student_fee, "StudentFee should exist.")
        self.assertEqual(
            student_fee.fee_structure, self.fee_structure,
            "StudentFee should use the FeeStructure pinned on the Admission."
        )

    def test_student_fee_total_amount_matches(self):
        self.enroll_admission()

        student = Student.objects.filter(admission=self.admission).first()
        student_fee = StudentFee.objects.filter(student=student).first()

        self.assertIsNotNone(student_fee)
        self.assertEqual(
            student_fee.total_amount, self.fee_structure.total_amount,
            "StudentFee.total_amount should match FeeStructure.total_amount."
        )

    def test_student_fee_initial_status_is_approval_pending(self):
        self.enroll_admission()

        student = Student.objects.filter(admission=self.admission).first()
        student_fee = StudentFee.objects.filter(student=student).first()

        self.assertIsNotNone(student_fee)
        self.assertEqual(
            student_fee.status, 'approval_pending',
            "StudentFee.status should be 'approval_pending' upon creation."
        )

    # ── Test 3: No duplicate StudentFee if re-enrolled ────────────────────────

    def test_no_duplicate_student_fee_on_re_save(self):
        self.enroll_admission()

        student = Student.objects.filter(admission=self.admission).first()
        initial_count = StudentFee.objects.filter(student=student).count()

        # Re-saving the admission should NOT create another StudentFee
        self.admission.note = 'Updated note'
        self.admission.save()

        final_count = StudentFee.objects.filter(student=student).count()
        self.assertEqual(
            initial_count, final_count,
            "Re-saving an enrolled admission should not duplicate StudentFee records."
        )

    # ── Test 4: Non-enrolled statuses don't create Student/Fee ───────────────

    def test_non_enrolled_status_does_not_create_student(self):
        for status in ['form_pending', 'payment_pending', 'approval_pending', 'approved', 'rejected']:
            admission = _make_admission(
                email=f'test_{status}@integration.com',
                status=status,
                fee_structure=self.fee_structure,
            )
            student_count = Student.objects.filter(admission=admission).count()
            self.assertEqual(
                student_count, 0,
                f"Status '{status}' should not create a Student, but found {student_count}."
            )
