from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
import json

from auth_user.models import Organization
from branch.models import Branch
from batches.models import Course, Subject, Batch
from students.models import Student
from leads.models import Lead
from onboarding.models import Admission
from datetime import date

User = get_user_model()

class MultiTenancyIsolationTest(TestCase):
    """
    Verifies that data belonging to one organization is never
    visible to users of another organization.
    Specifically, testing that implicit relational scoping works correctly.
    """

    def setUp(self):
        # Set up Organization A
        self.org_a = Organization.objects.create(name='Org A')
        self.branch_a = Branch.objects.create(organization=self.org_a, name='Branch A', code='BR_A')
        self.sa_a = User.objects.create_user(
            username='admin_a', email='admin_a@test.com', password='pass',
            role='super_admin', organization=self.org_a, is_active=True
        )

        # Set up Organization B
        self.org_b = Organization.objects.create(name='Org B')
        self.branch_b = Branch.objects.create(organization=self.org_b, name='Branch B', code='BR_B')
        self.sa_b = User.objects.create_user(
            username='admin_b', email='admin_b@test.com', password='pass',
            role='super_admin', organization=self.org_b, is_active=True
        )

        # Create data for Org A
        self.course_a = Course.objects.create(organization=self.org_a, name='Course A', code='C_A', course_type='cseet')
        self.batch_a = Batch.objects.create(
            organization=self.org_a, course=self.course_a, name='Batch A', batch_code='B_A',
            start_date=date.today(), end_date=date.today()
        )
        self.lead_a = Lead.objects.create(branch=self.branch_a, first_name='Lead', surname='A', phone_student='11111')

        # Create Admission + Student for Org A
        self.admission_a = Admission.objects.create(
            branch=self.branch_a, first_name='Student', surname='A', father_name='F_A',
            mother_name='M_A', dob=date.today(), category='general',
            email='stud_a@test.com', email_parent='par_a@test.com',
            phone_student='11111', phone_father='22222',
            street='Street A', city='City A', state='State A', pincode='111111',
            country='India', course='cseet', group_module='module_1',
            batch_attempt='may_25', location='Mumbai', qualification='graduate',
            reference='website', consent=True,
            tenth_medium='cbse', tenth_school='School A',
            tenth_percentage=80, tenth_percentile=85,
            twelfth_medium='cbse', twelfth_school='School A',
            twelfth_percentage=80, twelfth_percentile=85,
            doc_signature='sig.pdf', doc_photo='photo.jpg',
            doc_dob_certificate='dob.pdf', doc_id_card='id.pdf',
        )
        self.student_a = Student.objects.create(
            admission=self.admission_a, user=self.sa_a, branch=self.branch_a,
            first_name='Student', surname='A', father_name='F_A', mother_name='M_A',
            dob=date.today(), category='general', email='stud_a@test.com',
            phone_student='11111', phone_father='22222',
            street='Street A', city='City A', state='State A', pincode='111111',
            course='cseet', group_module='module_1', batch_attempt='may_25',
            qualification='graduate', location='Mumbai',
        )

        # Create data for Org B
        self.course_b = Course.objects.create(organization=self.org_b, name='Course B', code='C_B', course_type='cseet')
        self.batch_b = Batch.objects.create(
            organization=self.org_b, course=self.course_b, name='Batch B', batch_code='B_B',
            start_date=date.today(), end_date=date.today()
        )
        self.lead_b = Lead.objects.create(branch=self.branch_b, first_name='Lead', surname='B', phone_student='22222')

        # Create Admission + Student for Org B
        self.admission_b = Admission.objects.create(
            branch=self.branch_b, first_name='Student', surname='B', father_name='F_B',
            mother_name='M_B', dob=date.today(), category='general',
            email='stud_b@test.com', email_parent='par_b@test.com',
            phone_student='33333', phone_father='44444',
            street='Street B', city='City B', state='State B', pincode='222222',
            country='India', course='cseet', group_module='module_1',
            batch_attempt='may_25', location='Delhi', qualification='graduate',
            reference='website', consent=True,
            tenth_medium='cbse', tenth_school='School B',
            tenth_percentage=80, tenth_percentile=85,
            twelfth_medium='cbse', twelfth_school='School B',
            twelfth_percentage=80, twelfth_percentile=85,
            doc_signature='sig.pdf', doc_photo='photo.jpg',
            doc_dob_certificate='dob.pdf', doc_id_card='id.pdf',
        )
        self.student_b = Student.objects.create(
            admission=self.admission_b, user=self.sa_b, branch=self.branch_b,
            first_name='Student', surname='B', father_name='F_B', mother_name='M_B',
            dob=date.today(), category='general', email='stud_b@test.com',
            phone_student='33333', phone_father='44444',
            street='Street B', city='City B', state='State B', pincode='222222',
            course='cseet', group_module='module_1', batch_attempt='may_25',
            qualification='graduate', location='Delhi',
        )

        from rest_framework_simplejwt.tokens import AccessToken
        self.client_a = Client(HTTP_AUTHORIZATION=f'Bearer {str(AccessToken.for_user(self.sa_a))}')
        self.client_b = Client(HTTP_AUTHORIZATION=f'Bearer {str(AccessToken.for_user(self.sa_b))}')

    def test_branch_isolation(self):
        # Admin A should only see Branch A
        response_a = self.client_a.get('/api/v1/branches/')
        self.assertEqual(response_a.status_code, 200)
        data_a = response_a.json()
        self.assertEqual(len(data_a), 1)
        self.assertEqual(data_a[0]['name'], 'Branch A')

        # Admin B should only see Branch B
        response_b = self.client_b.get('/api/v1/branches/')
        self.assertEqual(response_b.status_code, 200)
        data_b = response_b.json()
        self.assertEqual(len(data_b), 1)
        self.assertEqual(data_b[0]['name'], 'Branch B')

    def test_course_isolation(self):
        # Admin A should only see Course A
        response_a = self.client_a.get('/api/v1/courses/')
        self.assertEqual(response_a.status_code, 200)
        data_a = response_a.json()
        self.assertEqual(data_a['count'], 1)
        self.assertEqual(data_a['data'][0]['name'], 'Course A')

        # Admin B should only see Course B
        response_b = self.client_b.get('/api/v1/courses/')
        self.assertEqual(response_b.status_code, 200)
        data_b = response_b.json()
        self.assertEqual(data_b['count'], 1)
        self.assertEqual(data_b['data'][0]['name'], 'Course B')

    def test_batch_isolation(self):
        # Admin A should only see Batch A
        response_a = self.client_a.get('/api/v1/batches/')
        self.assertEqual(response_a.status_code, 200)
        data_a = response_a.json()
        self.assertEqual(data_a['count'], 1)
        self.assertEqual(data_a['data'][0]['name'], 'Batch A')

        # Admin B should only see Batch B
        response_b = self.client_b.get('/api/v1/batches/')
        self.assertEqual(response_b.status_code, 200)
        data_b = response_b.json()
        self.assertEqual(data_b['count'], 1)
        self.assertEqual(data_b['data'][0]['name'], 'Batch B')

    def test_lead_isolation(self):
        # Admin A should only see Lead A
        response_a = self.client_a.get('/api/v1/leads/')
        self.assertEqual(response_a.status_code, 200)
        data_a = response_a.json()
        self.assertEqual(data_a['count'], 1)
        self.assertEqual(data_a['data'][0]['first_name'], 'Lead')
        self.assertEqual(data_a['data'][0]['surname'], 'A')

        # Admin B should only see Lead B
        response_b = self.client_b.get('/api/v1/leads/')
        self.assertEqual(response_b.status_code, 200)
        data_b = response_b.json()
        self.assertEqual(data_b['count'], 1)
        self.assertEqual(data_b['data'][0]['surname'], 'B')

    def test_student_isolation(self):
        # Admin A should only see Student A
        response_a = self.client_a.get('/api/v1/students/')
        self.assertEqual(response_a.status_code, 200)
        data_a = response_a.json()
        self.assertEqual(data_a['count'], 1)
        self.assertEqual(data_a['data'][0]['full_name'], 'Student A')

        # Admin B should only see Student B
        response_b = self.client_b.get('/api/v1/students/')
        self.assertEqual(response_b.status_code, 200)
        data_b = response_b.json()
        self.assertEqual(data_b['count'], 1)
        self.assertEqual(data_b['data'][0]['full_name'], 'Student B')
