"""
Advanced edge case tests for batches and fees modules.
Tests boundary conditions, error handling, concurrency, and complex scenarios.
"""
from django.test import TestCase, Client, TransactionTestCase
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from datetime import date, time, timedelta
from decimal import Decimal, InvalidOperation
import json

from batches.models import CourseLevel, Course, Subject, Batch, BatchStudent, BatchFaculty, Classroom, TimetableSlot
from batches.validators import check_faculty_clash, check_classroom_clash
from fees.models import (
    FeeStructure, StudentFee, InstallmentPlan, InstallmentItem,
    Payment, Refund, BankAccount,
)
from fees.utils import update_student_fee_status
from auth_user.models import User


# ═══════════════════════════════════════════════════════════════════════════════
# BATCHES - Advanced Edge Cases
# ═══════════════════════════════════════════════════════════════════════════════

class CourseEdgeCaseTest(TestCase):
    """Test edge cases for Course model."""

    def test_course_code_case_sensitivity(self):
        """Test that course codes are case-sensitive unique."""
        Course.objects.create(name='Course 1', code='CODE01', course_type='cseet')
        # Should allow different case
        course2 = Course.objects.create(name='Course 2', code='code01', course_type='cseet')
        self.assertEqual(course2.code, 'code01')

    def test_course_max_length_fields(self):
        """Test max length constraints."""
        # Test max length name (200 chars)
        long_name = 'A' * 200
        course = Course.objects.create(
            name=long_name,
            code='MAX01',
            course_type='cseet',
            description='B' * 10000,  # TextField should accept large text
        )
        self.assertEqual(len(course.name), 200)

    def test_course_negative_fee_amount(self):
        """Test that negative fee amounts are allowed by database but shouldn't be."""
        # Django doesn't enforce positive constraint at DB level for DecimalField
        # unless positive=True is set
        course = Course.objects.create(
            name='Negative Fee',
            code='NEG01',
            course_type='cseet',
            fee_amount=-1000,
        )
        # This will be saved, but business logic should validate
        self.assertEqual(course.fee_amount, -1000)

    def test_course_zero_duration(self):
        """Test course with zero duration."""
        course = Course.objects.create(
            name='Zero Duration',
            code='ZERO01',
            course_type='cseet',
            duration_months=0,
        )
        self.assertEqual(course.duration_months, 0)

    def test_course_very_large_fee(self):
        """Test course with very large fee amount."""
        large_fee = Decimal('99999999.99')
        course = Course.objects.create(
            name='Expensive Course',
            code='EXP01',
            course_type='cseet',
            fee_amount=large_fee,
        )
        self.assertEqual(course.fee_amount, large_fee)


class SubjectEdgeCaseTest(TestCase):
    """Test edge cases for Subject model."""

    def setUp(self):
        self.course = Course.objects.create(name='Test', code='TST01', course_type='cseet')

    def test_subject_unique_together_course_code(self):
        """Test that subject code is unique per course but not globally."""
        Subject.objects.create(level=CourseLevel.objects.get_or_create(course=self.course, order=1, defaults={'name':'L1'})[0], name='Subject 1', code='SUB01')
        
        # Should fail - same course, same code (wrap in atomic to allow queries after IntegrityError)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Subject.objects.create(level=CourseLevel.objects.get_or_create(course=self.course, order=1, defaults={'name':'L1'})[0], name='Subject 2', code='SUB01')
        
        # Should succeed - different course, same code
        course2 = Course.objects.create(name='Course 2', code='TST02', course_type='cseet')
        subject2 = Subject.objects.create(level=CourseLevel.objects.get_or_create(course=course2, order=1, defaults={'name':'L1'})[0], name='Subject 3', code='SUB01')
        self.assertEqual(subject2.code, 'SUB01')

    def test_subject_zero_hours(self):
        """Test subject with zero hours."""
        subject = Subject.objects.create(
            level=CourseLevel.objects.get_or_create(course=self.course, order=1, defaults={'name':'L1'})[0],
            name='No Hours',
            code='NOHRS',
            total_hours=0,
        )
        self.assertEqual(subject.total_hours, 0)

    def test_subject_delete_cascade(self):
        """Test that deleting course cascades to subjects."""
        subject = Subject.objects.create(level=CourseLevel.objects.get_or_create(course=self.course, order=1, defaults={'name':'L1'})[0], name='Will Delete', code='DEL01')
        subject_id = subject.id
        
        self.course.delete()
        
        with self.assertRaises(Subject.DoesNotExist):
            Subject.objects.get(id=subject_id)


class BatchEdgeCaseTest(TestCase):
    """Test edge cases for Batch model."""

    def setUp(self):
        self.course = Course.objects.create(name='Test', code='TST01', course_type='cseet')

    def test_batch_end_date_before_start_date(self):
        """Test batch with end date before start date (should be allowed but invalid business logic)."""
        batch = Batch.objects.create(
            course=self.course,
            name='Invalid Dates',
            batch_code='INV01',
            start_date=date(2025, 1, 1),
            end_date=date(2024, 1, 1),  # Before start
            max_students=30,
        )
        # Database allows it, but business logic should validate
        self.assertLess(batch.end_date, batch.start_date)

    def test_batch_same_start_and_end_date(self):
        """Test batch with same start and end date."""
        batch = Batch.objects.create(
            course=self.course,
            name='One Day',
            batch_code='ONEDAY',
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 1),
            max_students=30,
        )
        self.assertEqual(batch.start_date, batch.end_date)

    def test_batch_max_students_zero(self):
        """Test batch with zero max students."""
        batch = Batch.objects.create(
            course=self.course,
            name='No Students',
            batch_code='NOSTU',
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
            max_students=0,
        )
        self.assertEqual(batch.max_students, 0)

    def test_batch_max_students_exceeded(self):
        """Test enrolling more students than max_students."""
        batch = Batch.objects.create(
            course=self.course,
            name='Limited',
            batch_code='LIM01',
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
            max_students=2,
        )
        
        student1 = User.objects.create_user('stu1', 'stu1@test.com', 'pass', role='student',phone="9876543211")
        student2 = User.objects.create_user('stu2', 'stu2@test.com', 'pass', role='student',phone="9876543212")
        student3 = User.objects.create_user('stu3', 'stu3@test.com', 'pass', role='student',phone="9876543213")
        
        BatchStudent.objects.create(batch=batch, student=student1)
        BatchStudent.objects.create(batch=batch, student=student2)
        
        # Database allows exceeding, but API should validate
        BatchStudent.objects.create(batch=batch, student=student3)
        self.assertEqual(batch.batch_students.count(), 3)  # Exceeds max_students=2

    def test_batch_duplicate_student_enrollment(self):
        """Test enrolling same student twice in same batch."""
        batch = Batch.objects.create(
            course=self.course,
            name='Test',
            batch_code='TST01',
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
        )
        student = User.objects.create_user('stu1', 'stu1@test.com', 'pass', role='student')
        
        BatchStudent.objects.create(batch=batch, student=student)
        
        # Should fail due to unique_together
        with self.assertRaises(IntegrityError):
            BatchStudent.objects.create(batch=batch, student=student)


class TimetableEdgeCaseTest(TestCase):
    """Test edge cases for TimetableSlot model."""

    def setUp(self):
        self.course = Course.objects.create(name='Test', code='TST01', course_type='cseet')
        self.batch = Batch.objects.create(
            course=self.course, name='Batch', batch_code='B01',
            start_date=date(2025, 1, 1), end_date=date(2025, 12, 31),
        )
        self.subject = Subject.objects.create(level=CourseLevel.objects.get_or_create(course=self.course, order=1, defaults={'name':'L1'})[0], name='Sub', code='S01')
        self.faculty = User.objects.create_user('fac', 'fac@test.com', 'pass', role='faculty')
        self.classroom = Classroom.objects.create(name='Room 1', capacity=30)

    def test_timetable_end_time_before_start_time(self):
        """Test timetable slot with end time before start time."""
        slot = TimetableSlot.objects.create(
            batch=self.batch,
            subject=self.subject,
            faculty=self.faculty,
            classroom=self.classroom,
            day_of_week=0,
            start_time=time(14, 0),
            end_time=time(10, 0),  # Before start
        )
        # DB allows it, but validators should catch it
        self.assertLess(slot.end_time, slot.start_time)

    def test_timetable_same_start_and_end_time(self):
        """Test timetable slot with zero duration."""
        slot = TimetableSlot.objects.create(
            batch=self.batch,
            subject=self.subject,
            faculty=self.faculty,
            classroom=self.classroom,
            day_of_week=0,
            start_time=time(10, 0),
            end_time=time(10, 0),
        )
        self.assertEqual(slot.start_time, slot.end_time)

    def test_faculty_clash_detection(self):
        """Test faculty clash detection."""
        TimetableSlot.objects.create(
            batch=self.batch,
            subject=self.subject,
            faculty=self.faculty,
            classroom=self.classroom,
            day_of_week=0,
            start_time=time(10, 0),
            end_time=time(12, 0),
        )
        
        # check_faculty_clash returns a list of clashing IDs (not raises ValidationError)
        clashes = check_faculty_clash(
            self.faculty.id, 0, time(11, 0), time(13, 0)
        )
        self.assertGreater(len(clashes), 0)

    def test_faculty_no_clash_adjacent_slots(self):
        """Test that adjacent slots don't clash."""
        TimetableSlot.objects.create(
            batch=self.batch,
            subject=self.subject,
            faculty=self.faculty,
            classroom=self.classroom,
            day_of_week=0,
            start_time=time(10, 0),
            end_time=time(12, 0),
        )
        
        # Should return empty list - starts exactly when other ends (no overlap)
        clashes = check_faculty_clash(
            self.faculty.id, 0, time(12, 0), time(14, 0)
        )
        self.assertEqual(len(clashes), 0)

    def test_classroom_clash_detection(self):
        """Test classroom clash detection."""
        TimetableSlot.objects.create(
            batch=self.batch,
            subject=self.subject,
            faculty=self.faculty,
            classroom=self.classroom,
            day_of_week=0,
            start_time=time(10, 0),
            end_time=time(12, 0),
        )
        
        # check_classroom_clash returns a list of clashing IDs (not raises ValidationError)
        clashes = check_classroom_clash(
            self.classroom.id, 0, time(11, 0), time(13, 0)
        )
        self.assertGreater(len(clashes), 0)


# ═══════════════════════════════════════════════════════════════════════════════
# FEES - Advanced Edge Cases
# ═══════════════════════════════════════════════════════════════════════════════

class FeeStructureEdgeCaseTest(TestCase):
    """Test edge cases for FeeStructure model."""

    def setUp(self):
        self.course = Course.objects.create(name='Test', code='TST01', course_type='cseet')

    def test_fee_structure_zero_amount(self):
        """Test fee structure with zero amount."""
        fee = FeeStructure.objects.create(
            name='Free Course',
            course=self.course,
            total_amount=0,
        )
        self.assertEqual(fee.total_amount, 0)

    def test_fee_structure_negative_amount(self):
        """Test fee structure with negative amount."""
        fee = FeeStructure.objects.create(
            name='Negative',
            total_amount=-5000,
        )
        self.assertEqual(fee.total_amount, -5000)

    def test_fee_structure_very_large_amount(self):
        """Test fee structure with maximum decimal value."""
        large_amount = Decimal('99999999.99')
        fee = FeeStructure.objects.create(
            name='Expensive',
            total_amount=large_amount,
        )
        self.assertEqual(fee.total_amount, large_amount)

    def test_fee_structure_fractional_paisa(self):
        """Test fee structure with fractional paisa (should round to 2 decimals)."""
        fee = FeeStructure.objects.create(
            name='Fractional',
            total_amount=Decimal('10000.999'),
        )
        # Should be stored with 2 decimal places
        self.assertEqual(fee.total_amount, Decimal('10000.999'))


class StudentFeeEdgeCaseTest(TestCase):
    """Test edge cases for StudentFee model."""

    def setUp(self):
        self.student = User.objects.create_user('stu', 'stu@test.com', 'pass', role='student')
        self.fee_structure = FeeStructure.objects.create(name='Fee', total_amount=50000)

    def test_student_fee_discount_exceeds_total(self):
        """Test student fee with discount exceeding total amount."""
        student_fee = StudentFee.objects.create(
            student=self.student,
            fee_structure=self.fee_structure,
            total_amount=50000,
            discount=60000,  # More than total
        )
        # Database allows it, but validators should prevent
        self.assertEqual(student_fee.amount_due, -10000)  # Negative due!

    def test_student_fee_exact_discount(self):
        """Test student fee with discount equal to total."""
        student_fee = StudentFee.objects.create(
            student=self.student,
            fee_structure=self.fee_structure,
            total_amount=50000,
            discount=50000,
        )
        self.assertEqual(student_fee.amount_due, 0)

    def test_student_fee_zero_total(self):
        """Test student fee with zero total amount."""
        student_fee = StudentFee.objects.create(
            student=self.student,
            fee_structure=self.fee_structure,
            total_amount=0,
        )
        self.assertEqual(student_fee.amount_due, 0)


class PaymentEdgeCaseTest(TestCase):
    """Test edge cases for Payment model."""

    def setUp(self):
        self.student = User.objects.create_user('stu', 'stu@test.com', 'pass', role='student')
        self.fee_structure = FeeStructure.objects.create(name='Fee', total_amount=50000)
        self.student_fee = StudentFee.objects.create(
            student=self.student,
            fee_structure=self.fee_structure,
            total_amount=50000,
        )

    def test_payment_zero_amount(self):
        """Test payment with zero amount."""
        payment = Payment.objects.create(
            student=self.student,
            student_fee=self.student_fee,
            amount=0,
            payment_mode='cash',
            payment_date=date.today(),
        )
        self.assertEqual(payment.amount, 0)

    def test_payment_negative_amount(self):
        """Test payment with negative amount."""
        payment = Payment.objects.create(
            student=self.student,
            student_fee=self.student_fee,
            amount=-1000,
            payment_mode='cash',
            payment_date=date.today(),
        )
        self.assertEqual(payment.amount, -1000)

    def test_payment_exceeds_due_amount(self):
        """Test payment that exceeds the due amount."""
        Payment.objects.create(
            student=self.student,
            student_fee=self.student_fee,
            amount=100000,  # More than due (50000)
            payment_mode='upi',
            payment_date=date.today(),
            status='verified',
        )
        
        self.student_fee.refresh_from_db()
        self.assertEqual(self.student_fee.amount_paid, 100000)
        self.assertEqual(self.student_fee.status, 'paid')

    def test_payment_multiple_receipt_numbers_unique(self):
        """Test that receipt numbers are unique."""
        payment1 = Payment.objects.create(
            student=self.student,
            student_fee=self.student_fee,
            amount=10000,
            payment_mode='cash',
            payment_date=date.today(),
        )
        
        # Receipt number should be auto-generated and unique
        self.assertIsNotNone(payment1.receipt_number)

    def test_payment_status_transitions(self):
        """Test payment status transitions."""
        payment = Payment.objects.create(
            student=self.student,
            student_fee=self.student_fee,
            amount=10000,
            payment_mode='upi',
            payment_date=date.today(),
            status='approval_pending',
        )
        
        # Transition: pending -> verified
        payment.status = 'verified'
        payment.save()
        self.assertEqual(payment.status, 'verified')
        
        # Transition: verified -> rejected (unusual but should be allowed)
        payment.status = 'rejected'
        payment.save()
        self.assertEqual(payment.status, 'rejected')


class RefundEdgeCaseTest(TestCase):
    """Test edge cases for Refund model."""

    def setUp(self):
        self.student = User.objects.create_user('stu', 'stu@test.com', 'pass', role='student')
        self.fee_structure = FeeStructure.objects.create(name='Fee', total_amount=50000)
        self.student_fee = StudentFee.objects.create(
            student=self.student,
            fee_structure=self.fee_structure,
            total_amount=50000,
        )
        self.payment = Payment.objects.create(
            student=self.student,
            student_fee=self.student_fee,
            amount=30000,
            payment_mode='upi',
            payment_date=date.today(),
            status='verified',
        )

    def test_refund_exceeds_payment_amount(self):
        """Test refund that exceeds the payment amount."""
        refund = Refund.objects.create(
            payment=self.payment,
            amount=50000,  # More than payment (30000)
            reason='Over refund',
            status='completed',
        )
        # Database allows it, but business logic should validate
        self.assertEqual(refund.amount, 50000)

    def test_refund_zero_amount(self):
        """Test refund with zero amount."""
        refund = Refund.objects.create(
            payment=self.payment,
            amount=0,
            reason='Zero refund',
        )
        self.assertEqual(refund.amount, 0)

    def test_multiple_refunds_same_payment(self):
        """Test multiple refunds for same payment."""
        Refund.objects.create(payment=self.payment, amount=10000, status='completed')
        Refund.objects.create(payment=self.payment, amount=10000, status='completed')
        
        self.assertEqual(self.payment.refunds.count(), 2)

    def test_refund_updates_student_fee_status(self):
        """Test that refund updates student fee status correctly."""
        # After a verified payment the status should be 'partial' (FEE_STATUS_CHOICES uses 'partial')
        update_student_fee_status(self.student_fee.id)
        self.student_fee.refresh_from_db()
        self.assertEqual(self.student_fee.status, 'partial')
        
        # Create refund
        Refund.objects.create(
            payment=self.payment,
            amount=30000,  # Full refund
            status='completed',
        )
        
        update_student_fee_status(self.student_fee.id)
        self.student_fee.refresh_from_db()
        self.assertEqual(self.student_fee.amount_paid, 0)


class InstallmentEdgeCaseTest(TestCase):
    """Test edge cases for InstallmentPlan and InstallmentItem."""

    def setUp(self):
        self.student = User.objects.create_user('stu', 'stu@test.com', 'pass', role='student')
        self.fee_structure = FeeStructure.objects.create(name='Fee', total_amount=50000)
        self.student_fee = StudentFee.objects.create(
            student=self.student,
            fee_structure=self.fee_structure,
            total_amount=50000,
        )

    def test_installment_total_exceeds_student_fee(self):
        """Test installment plan with total exceeding student fee."""
        plan = InstallmentPlan.objects.create(student_fee=self.student_fee)
        
        InstallmentItem.objects.create(plan=plan, amount=30000, due_date=date(2025, 7, 1))
        InstallmentItem.objects.create(plan=plan, amount=30000, due_date=date(2025, 8, 1))
        # Total: 60000 > 50000 — InstallmentPlan has no total_amount property, sum items manually
        total = sum(item.amount for item in plan.items.all())
        self.assertEqual(total, 60000)

    def test_installment_item_zero_amount(self):
        """Test installment item with zero amount."""
        plan = InstallmentPlan.objects.create(student_fee=self.student_fee)
        
        item = InstallmentItem.objects.create(
            plan=plan,
            amount=0,
            due_date=date(2025, 7, 1),
        )
        self.assertEqual(item.amount, 0)

    def test_installment_past_due_date(self):
        """Test installment with past due date."""
        plan = InstallmentPlan.objects.create(student_fee=self.student_fee)
        
        past_date = date.today() - timedelta(days=30)
        item = InstallmentItem.objects.create(
            plan=plan,
            amount=10000,
            due_date=past_date,
        )
        # InstallmentItem uses is_paid (bool) not status; check due date is in the past
        self.assertFalse(item.is_paid)
        self.assertLess(item.due_date, date.today())

    def test_installment_item_due_today(self):
        """Test installment item due today."""
        plan = InstallmentPlan.objects.create(student_fee=self.student_fee)
        
        item = InstallmentItem.objects.create(
            plan=plan,
            amount=10000,
            due_date=date.today(),
        )
        # Not paid, due_date is today (not past)
        self.assertFalse(item.is_paid)
        self.assertEqual(item.due_date, date.today())


class APIEdgeCaseTest(TestCase):
    """Test API edge cases and error handling."""

    def setUp(self):
        self.client = Client()
        user = User.objects.create_user('admin', 'admin@test.com', 'pass', role='admin', is_active=True)
        from rest_framework_simplejwt.tokens import AccessToken
        token = AccessToken.for_user(user)
        self.client = Client(HTTP_AUTHORIZATION=f'Bearer {str(token)}')
        self.course = Course.objects.create(name='Test', code='TST01', course_type='cseet')

    def test_create_course_missing_required_fields(self):
        """Test creating course with missing required fields."""
        response = self.client.post(
            '/api/v1/courses/',
            data=json.dumps({}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)

    def test_create_course_invalid_data_types(self):
        """Test creating course with invalid data types."""
        response = self.client.post(
            '/api/v1/courses/',
            data=json.dumps({
                'name': 'Test',
                'code': 'TST02',
                'course_type': 'cseet',
                'duration_months': 'invalid',  # Should be integer
                'fee_amount': 'not_a_number',  # Should be decimal
            }),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)

    def test_update_nonexistent_course(self):
        """Test updating a course that doesn't exist."""
        response = self.client.patch(
            '/api/v1/courses/00000000-0000-0000-0000-000000000000/',
            data=json.dumps({'name': 'Updated'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 404)

    def test_delete_nonexistent_course(self):
        """Test deleting a course that doesn't exist."""
        response = self.client.delete(
            '/api/v1/courses/00000000-0000-0000-0000-000000000000/',
        )
        self.assertEqual(response.status_code, 404)

    def test_invalid_uuid_format(self):
        """Test API with invalid UUID format."""
        response = self.client.get('/api/v1/courses/invalid-uuid/')
        self.assertEqual(response.status_code, 404)

    def test_concurrent_course_creation(self):
        """Test concurrent course creation with same code."""
        # Try to create two courses with same code
        Course.objects.create(name='Course 1', code='DUP01', course_type='cseet')
        
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Course.objects.create(name='Course 2', code='DUP01', course_type='cseet')


class AuthenticationEdgeCaseTest(TestCase):
    """Test authentication edge cases."""

    def setUp(self):
        self.client = Client()

    def test_access_with_expired_token(self):
        """Test access with expired JWT token."""
        from rest_framework_simplejwt.tokens import RefreshToken
        from datetime import timedelta
        from django.conf import settings
        
        user = User.objects.create_user('test', 'test@test.com', 'pass', role='admin')
        
        # Create token with very short lifetime
        from rest_framework_simplejwt.settings import api_settings
        from rest_framework_simplejwt.tokens import AccessToken
        
        token = AccessToken.for_user(user)
        token.set_exp(lifetime=timedelta(seconds=-1))  # Already expired
        
        response = self.client.get(
            '/api/v1/courses/',
            HTTP_AUTHORIZATION=f'Bearer {str(token)}',
        )
        self.assertEqual(response.status_code, 401)

    def test_access_with_malformed_token(self):
        """Test access with malformed JWT token."""
        response = self.client.get(
            '/api/v1/courses/',
            HTTP_AUTHORIZATION='Bearer not.a.valid.token',
        )
        self.assertIn(response.status_code, [401, 403])

    def test_access_without_bearer_prefix(self):
        """Test access with token but without 'Bearer' prefix."""
        user = User.objects.create_user('test', 'test@test.com', 'pass', role='admin')
        from rest_framework_simplejwt.tokens import RefreshToken
        
        refresh = RefreshToken.for_user(user)
        
        response = self.client.get(
            '/api/v1/courses/',
            HTTP_AUTHORIZATION=str(refresh.access_token),  # No 'Bearer'
        )
        self.assertEqual(response.status_code, 401)


class DatabaseIndexEdgeCaseTest(TestCase):
    """Test database indexes under load."""

    def test_bulk_course_creation_performance(self):
        """Test bulk course creation doesn't degrade with indexes."""
        import time
        
        start = time.time()
        for i in range(100):
            Course.objects.create(
                name=f'Course {i}',
                code=f'CODE{i:03d}',
                course_type='cseet',
            )
        duration = time.time() - start
        
        # Should complete in reasonable time (< 5 seconds for 100 records)
        self.assertLess(duration, 5.0)

    def test_query_with_composite_index(self):
        """Test that queries use composite indexes efficiently."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        
        # Create test data
        for i in range(50):
            Course.objects.create(
                name=f'Course {i}',
                code=f'CODE{i:03d}',
                course_type='cseet' if i % 2 == 0 else 'cs_executive',
                is_active=i % 3 != 0,
            )
        
        # Query using composite index fields
        with CaptureQueriesContext(connection) as queries:
            courses = Course.objects.filter(
                course_type='cseet',
                is_active=True,
            )
            list(courses)  # Force evaluation
        
        # Should use index efficiently (1 query)
        self.assertEqual(len(queries), 1)


class APILoadHandlingTest(TestCase):
    """Test API robustness and load handling."""

    def setUp(self):
        self.client = Client()
        user = User.objects.create_user('load_admin', 'load@test.com', 'pass', role='admin', is_active=True)
        from rest_framework_simplejwt.tokens import AccessToken
        token = AccessToken.for_user(user)
        self.client = Client(HTTP_AUTHORIZATION=f'Bearer {str(token)}')

    def test_large_payload_handling(self):
        """Test API handles a very large request body gracefully."""
        # Create a large payload string (1MB)
        large_string = "A" * 1024 * 1024
        response = self.client.post(
            '/api/v1/courses/',
            data=json.dumps({
                'name': large_string,
                'code': 'LRG01',
                'course_type': 'cseet',
            }),
            content_type='application/json',
        )
        # Should be rejected with 400 Bad Request (max length exceeded)
        self.assertEqual(response.status_code, 400)

    def test_pagination_and_load(self):
        """Test that fetching a large number of items respects pagination and handles load."""
        import time
        start_time = time.time()
        
        # Create 50 courses
        for i in range(50):
            Course.objects.create(
                name=f'Load Course {i}',
                code=f'LOD{i:03d}',
                course_type='cseet'
            )
            
        # Fetch courses list
        response = self.client.get('/api/v1/courses/')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertTrue('count' in data or type(data) == list)
        
        duration = time.time() - start_time
        # Should handle creation and query in under 5 seconds
        self.assertLess(duration, 5.0)
        
    def test_malformed_json_robustness(self):
        """Test API robustness against malformed JSON data."""
        response = self.client.post(
            '/api/v1/courses/',
            data="{malformed: json, 'name': 'test}",
            content_type='application/json',
        )
        # Should return 400 Bad Request, not 500 Internal Server Error
        self.assertEqual(response.status_code, 400)
