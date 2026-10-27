import datetime
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status

from auth_user.models import User, Organization
from branch.models import Branch
from attendance.models import EmployeeAttendanceRecord


class EmployeeAttendanceDetailAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name="Detail Test Org")
        self.branch = Branch.objects.create(
            name="Detail Test Branch",
            organization=self.org,
            latitude=19.0760,
            longitude=72.8777,
            allowed_radius_meters=1000
        )

        self.admin = User.objects.create_user(
            username="admin_detail_test",
            email="admin_detail@test.com",
            password="password123",
            role="super_admin",
            organization=self.org,
            branch=self.branch,
            name="Admin Detail",
            is_active=True
        )

        self.employee = User.objects.create_user(
            username="emp_detail_test",
            email="emp_detail@test.com",
            password="password123",
            role="admin_executive",
            organization=self.org,
            branch=self.branch,
            name="Employee Detail",
            is_active=True
        )

    def test_detail_api_methods_and_location_details(self):
        self.client.force_authenticate(user=self.admin)
        today = timezone.now().date()
        in_time = timezone.now().replace(hour=9, minute=0, second=0)
        out_time = timezone.now().replace(hour=18, minute=0, second=0)

        # Create record with both check in and check out location and method
        rec = EmployeeAttendanceRecord.objects.create(
            user=self.employee,
            branch=self.branch,
            date=today,
            status='present',
            checked_in_at=in_time,
            checked_out_at=out_time,
            check_in_method='qr',
            check_out_method='qr',
            latitude=19.0761,
            longitude=72.8778,
            location_verified=True,
            checkout_latitude=19.0765,
            checkout_longitude=72.8780,
            checkout_location_verified=True,
        )

        url = f"/api/v1/attendance/employee/{self.employee.id}/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data['data']

        # 1. Verify day_wise_attendance includes check_in_method & check_out_method
        day_att = data['day_wise_attendance']
        self.assertEqual(len(day_att), 1)
        item = day_att[0]
        self.assertEqual(item['check_in_method'], 'qr')
        self.assertEqual(item['check_in_method_display'], 'QR Scan')
        self.assertEqual(item['check_out_method'], 'qr')
        self.assertEqual(item['check_out_method_display'], 'QR Scan')

        # 2. Verify location_details includes ONLY check_in and check_out
        loc = item['location_details']
        self.assertIsNotNone(loc)
        self.assertIn('check_in', loc)
        self.assertIn('check_out', loc)
        self.assertEqual(set(loc.keys()), {'check_in', 'check_out'})
        self.assertEqual(round(loc['check_in']['latitude'], 4), 19.0761)
        self.assertEqual(round(loc['check_in']['longitude'], 4), 72.8778)
        self.assertTrue(loc['check_in']['location_verified'])
        self.assertEqual(round(loc['check_out']['latitude'], 4), 19.0765)
        self.assertEqual(round(loc['check_out']['longitude'], 4), 72.8780)
        self.assertTrue(loc['check_out']['location_verified'])
        self.assertNotIn('latitude', loc)
        self.assertNotIn('longitude', loc)

        # 3. Verify check_in_history and check_out_history
        self.assertEqual(len(data['check_in_history']), 1)
        self.assertEqual(data['check_in_history'][0]['check_in_method'], 'qr')
        self.assertEqual(round(data['check_in_history'][0]['latitude'], 4), 19.0761)

        self.assertEqual(len(data['check_out_history']), 1)
        self.assertEqual(data['check_out_history'][0]['check_out_method'], 'qr')
        self.assertEqual(round(data['check_out_history'][0]['latitude'], 4), 19.0765)

    def test_historical_record_checkout_location_resolution(self):
        """Verify historical records with checked_out_at but checkout_latitude=None still resolve check_out location."""
        self.client.force_authenticate(user=self.admin)
        today = timezone.now().date()
        in_time = timezone.now().replace(hour=9, minute=0, second=0)
        out_time = timezone.now().replace(hour=18, minute=0, second=0)

        # Historical record: checked out, but checkout_latitude is NULL in DB
        rec = EmployeeAttendanceRecord.objects.create(
            user=self.employee,
            branch=self.branch,
            date=today,
            status='present',
            checked_in_at=in_time,
            checked_out_at=out_time,
            check_in_method='qr',
            check_out_method='qr',
            latitude=23.052972,
            longitude=72.559006,
            location_verified=True,
            checkout_latitude=None,
            checkout_longitude=None,
        )

        url = f"/api/v1/attendance/employee/{self.employee.id}/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data['data']

        item = data['day_wise_attendance'][0]
        loc = item['location_details']
        self.assertIsNotNone(loc)
        self.assertIsNotNone(loc['check_in'])
        self.assertIsNotNone(loc['check_out'], "check_out must not be null when checked_out_at exists")
        self.assertEqual(round(loc['check_out']['latitude'], 4), 23.0530)
        self.assertEqual(round(loc['check_out']['longitude'], 4), 72.5590)
        self.assertTrue(loc['check_out']['location_verified'])

    def test_detail_api_date_filters(self):
        self.client.force_authenticate(user=self.admin)
        d1 = datetime.date(2026, 9, 15)
        d2 = datetime.date(2026, 10, 10)
        d3 = datetime.date(2026, 10, 20)

        EmployeeAttendanceRecord.objects.create(
            user=self.employee, branch=self.branch, date=d1, status='present'
        )
        EmployeeAttendanceRecord.objects.create(
            user=self.employee, branch=self.branch, date=d2, status='present'
        )
        EmployeeAttendanceRecord.objects.create(
            user=self.employee, branch=self.branch, date=d3, status='present'
        )

        base_url = f"/api/v1/attendance/employee/{self.employee.id}/"

        # Filter by single date
        r = self.client.get(f"{base_url}?date=2026-10-10")
        self.assertEqual(len(r.data['data']['day_wise_attendance']), 1)
        self.assertEqual(str(r.data['data']['day_wise_attendance'][0]['date']), "2026-10-10")

        # Filter by from_date / to_date
        r = self.client.get(f"{base_url}?from_date=2026-10-01&to_date=2026-10-31")
        self.assertEqual(len(r.data['data']['day_wise_attendance']), 2)

        # Filter by month (10)
        r = self.client.get(f"{base_url}?month=10")
        self.assertEqual(len(r.data['data']['day_wise_attendance']), 2)

        # Filter by month YYYY-MM
        r = self.client.get(f"{base_url}?month=2026-09")
        self.assertEqual(len(r.data['data']['day_wise_attendance']), 1)
        self.assertEqual(str(r.data['data']['day_wise_attendance'][0]['date']), "2026-09-15")

        # Filter by year
        r = self.client.get(f"{base_url}?year=2026")
        self.assertEqual(len(r.data['data']['day_wise_attendance']), 3)
