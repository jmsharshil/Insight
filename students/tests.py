from django.test import TestCase
from rest_framework.test import APIClient
from auth_user.models import User, Organization
from students.models import Student
from batches.models import Batch, Course
from onboarding.models import Admission
from branch.models import Branch

class FilterSearchTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name="Test Org")
        self.branch = Branch.objects.create(name="Test Branch", organization=self.org)
        self.super_user = User.objects.create_user(
            username='superadmin',
            email='super@test.com',
            password='password123',
            name='Super Admin',
            role='super_admin',
            organization=self.org
        )
        self.client.force_authenticate(user=self.super_user)

        self.course = Course.objects.create(name="Test Course", course_type="crash_course", organization=self.org)
        self.batch = Batch.objects.create(name="Test Batch", course=self.course, organization=self.org, is_active=True, start_date="2026-01-01", end_date="2026-12-31")

        self.student1_user = User.objects.create_user(username='stu1', email='stu1@test.com', password='password123', name='Alice', role='student')
        self.student2_user = User.objects.create_user(username='stu2', email='stu2@test.com', password='password123', name='Bob', role='student')

        self.admission1 = Admission.objects.create(first_name='Alice', email='stu1@test.com', branch=self.branch, course=self.course, dob="2010-01-01", status="enrolled", phone_student="1234567890", tenth_percentage=90)
        self.admission2 = Admission.objects.create(first_name='Bob', email='stu2@test.com', branch=self.branch, course=self.course, dob="2010-02-02", status="enrolled", phone_student="0987654321", tenth_percentage=85)

        self.student1 = Student.objects.create(user=self.student1_user, branch=self.branch, batch=self.batch, admission_number="A001", dob="2010-01-01", admission=self.admission1)
        self.student2 = Student.objects.create(user=self.student2_user, branch=self.branch, batch=self.batch, admission_number="A002", dob="2010-02-02", admission=self.admission2)

    def test_student_list_search(self):
        # Search for 'Alice'
        response = self.client.get('/api/v1/students/?search=Alice')
        self.assertEqual(response.status_code, 200)
        data = response.json().get('data', [])
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['user_name'], 'Alice')

        # Search for 'Bob'
        response = self.client.get('/api/v1/students/?search=Bob')
        self.assertEqual(response.status_code, 200)
        data = response.json().get('data', [])
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['user_name'], 'Bob')

    def test_student_list_filter(self):
        # Filter by branch
        response = self.client.get(f'/api/v1/students/?branch_id={self.branch.id}')
        self.assertEqual(response.status_code, 200)
        data = response.json().get('data', [])
        self.assertEqual(len(data), 2)

    def test_student_list_ordering(self):
        # Order by name
        response = self.client.get('/api/v1/students/?ordering=user__name')
        self.assertEqual(response.status_code, 200)
        data = response.json().get('data', [])
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]['user_name'], 'Alice')
        self.assertEqual(data[1]['user_name'], 'Bob')

        # Reverse ordering
        response = self.client.get('/api/v1/students/?ordering=-user__name')
        self.assertEqual(response.status_code, 200)
        data = response.json().get('data', [])
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]['user_name'], 'Bob')
        self.assertEqual(data[1]['user_name'], 'Alice')
