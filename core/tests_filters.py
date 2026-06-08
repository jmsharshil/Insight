from django.test import TestCase
from rest_framework.test import APIClient
from auth_user.models import User, Organization
from batches.models import Course

class GenericFilterSearchTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name="Test Org")
        self.super_user = User.objects.create_user(
            username='superadmin',
            email='super@test.com',
            password='password123',
            name='Super Admin',
            role='super_admin',
            organization=self.org
        )
        self.client.force_authenticate(user=self.super_user)

        self.course1 = Course.objects.create(name="Crash Course 2026", course_type="cseet", organization=self.org, fee_amount=1000)
        self.course2 = Course.objects.create(name="Regular Course 2026", course_type="cs_executive", organization=self.org, fee_amount=2000)
        self.course3 = Course.objects.create(name="Crash Course 2027", course_type="cseet", organization=self.org, fee_amount=1500)

    def test_course_list_search(self):
        # Search for 'Regular'
        response = self.client.get('/api/v1/courses/?search=Regular')
        self.assertEqual(response.status_code, 200)
        data = response.json().get('data', [])
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['name'], 'Regular Course 2026')

        # Search for 'Crash'
        response = self.client.get('/api/v1/courses/?search=Crash')
        self.assertEqual(response.status_code, 200)
        data = response.json().get('data', [])
        self.assertEqual(len(data), 2)

    def test_course_list_filter(self):
        # Filter by course_type
        response = self.client.get('/api/v1/courses/?course_type=cseet')
        if response.status_code != 200:
            print("ERROR", response.content)
        self.assertEqual(response.status_code, 200)
        data = response.json().get('data', [])
        self.assertEqual(len(data), 2)

        response = self.client.get('/api/v1/courses/?course_type=cs_executive')
        self.assertEqual(response.status_code, 200)
        data = response.json().get('data', [])
        self.assertEqual(len(data), 1)

    def test_course_list_ordering(self):
        # Order by fee_amount
        response = self.client.get('/api/v1/courses/?ordering=fee_amount')
        self.assertEqual(response.status_code, 200)
        data = response.json().get('data', [])
        self.assertEqual(len(data), 3)
        self.assertEqual(data[0]['fee_amount'], '1000.00')
        self.assertEqual(data[1]['fee_amount'], '1500.00')
        self.assertEqual(data[2]['fee_amount'], '2000.00')

        # Order by fee_amount descending
        response = self.client.get('/api/v1/courses/?ordering=-fee_amount')
        self.assertEqual(response.status_code, 200)
        data = response.json().get('data', [])
        self.assertEqual(len(data), 3)
        self.assertEqual(data[0]['fee_amount'], '2000.00')
        self.assertEqual(data[1]['fee_amount'], '1500.00')
        self.assertEqual(data[2]['fee_amount'], '1000.00')
