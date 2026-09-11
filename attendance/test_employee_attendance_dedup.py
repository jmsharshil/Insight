import datetime
from unittest.mock import patch
from django.test import TestCase
from django.utils import timezone
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status

from auth_user.models import User, Organization
from branch.models import Branch
from attendance.models import EmployeeAttendanceRecord
from attendance.tasks import auto_mark_staff_absentees_eod


class EmployeeAttendanceDedupTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name="Test Org Dedup")
        self.branch = Branch.objects.create(
            name="Test Branch Dedup",
            organization=self.org,
            latitude=12.9716,
            longitude=77.5946,
            allowed_radius_meters=1000
        )

        # Admin user
        self.admin_user = User.objects.create_user(
            username="admin_dedup",
            email="admin_dedup@test.com",
            password="password123",
            role="super_admin",
            organization=self.org,
            branch=self.branch,
            name="Super Admin Dedup",
            is_active=True
        )

        # Staff user
        self.staff_user = User.objects.create_user(
            username="staff_dedup",
            email="staff_dedup@test.com",
            password="password123",
            role="admin_executive",
            organization=self.org,
            branch=self.branch,
            name="Staff User Dedup",
            is_active=True
        )

        # Staff user 2 (remains genuinely absent)
        self.absent_staff = User.objects.create_user(
            username="staff_absent_only",
            email="staff_absent_only@test.com",
            password="password123",
            role="admin_executive",
            organization=self.org,
            branch=self.branch,
            name="Absent Staff Dedup",
            is_active=True
        )

        self.today = timezone.localtime(timezone.now()).date()

    @patch('auditlog.blob_service.download_log_file', return_value=None)
    @patch('auditlog.blob_service.upload_log_file', return_value=True)
    def test_list_api_deduplicates_ghost_absent_record(self, mock_upload, mock_download):
        """
        When both an 'absent' entry and a 'present' entry exist for the staff member on the same day,
        the Employee Attendance List API should return only the active entry and exclude the ghost absent entry.
        """
        # Create ghost absent record
        EmployeeAttendanceRecord.objects.create(
            user=self.staff_user,
            branch=self.branch,
            date=self.today,
            status='absent'
        )
        # Create active present record
        EmployeeAttendanceRecord.objects.create(
            user=self.staff_user,
            branch=self.branch,
            date=self.today,
            status='present',
            checked_in_at=timezone.now(),
            checked_out_at=timezone.now()
        )
        # Create genuine absent record for staff 2
        EmployeeAttendanceRecord.objects.create(
            user=self.absent_staff,
            branch=self.branch,
            date=self.today,
            status='absent'
        )

        self.client.force_authenticate(user=self.admin_user)
        url = reverse('employee-attendance-list-create')
        response = self.client.get(f"{url}?user_id={self.staff_user.id}&date={self.today}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get('results', response.data.get('data', []))
        if isinstance(results, dict) and 'results' in results:
            results = results['results']

        # There should only be 1 entry for this staff member (present), not 2
        staff_records = [r for r in results if str(r.get('user', '')) == str(self.staff_user.id)]
        self.assertEqual(len(staff_records), 1)
        self.assertEqual(staff_records[0]['status'], 'present')

        # Staff 2 should still show absent
        response2 = self.client.get(f"{url}?user_id={self.absent_staff.id}&date={self.today}")
        results2 = response2.data.get('results', response2.data.get('data', []))
        if isinstance(results2, dict) and 'results' in results2:
            results2 = results2['results']
        self.assertEqual(len(results2), 1)
        self.assertEqual(results2[0]['status'], 'absent')

    @patch('auditlog.blob_service.download_log_file', return_value=None)
    @patch('auditlog.blob_service.upload_log_file', return_value=True)
    def test_history_api_deduplicates_ghost_absent_record(self, mock_upload, mock_download):
        """
        Employee Attendance History API should exclude ghost absent records from both records and summary.
        """
        EmployeeAttendanceRecord.objects.create(
            user=self.staff_user,
            branch=self.branch,
            date=self.today,
            status='absent'
        )
        EmployeeAttendanceRecord.objects.create(
            user=self.staff_user,
            branch=self.branch,
            date=self.today,
            status='present',
            checked_in_at=timezone.now(),
            checked_out_at=timezone.now()
        )

        self.client.force_authenticate(user=self.staff_user)
        url = reverse('employee-attendance-history')
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        summary = response.data.get('summary', {})
        records = response.data.get('records', [])

        self.assertEqual(summary.get('present_days'), 1)
        self.assertEqual(summary.get('absent_days'), 0)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['status'], 'present')

    @patch('auditlog.blob_service.download_log_file', return_value=None)
    @patch('auditlog.blob_service.upload_log_file', return_value=True)
    def test_detail_api_deduplicates_ghost_absent_record(self, mock_upload, mock_download):
        """
        Employee Attendance Detail API should exclude ghost absent records.
        """
        EmployeeAttendanceRecord.objects.create(
            user=self.staff_user,
            branch=self.branch,
            date=self.today,
            status='absent'
        )
        EmployeeAttendanceRecord.objects.create(
            user=self.staff_user,
            branch=self.branch,
            date=self.today,
            status='present',
            checked_in_at=timezone.now(),
            checked_out_at=timezone.now()
        )

        self.client.force_authenticate(user=self.admin_user)
        url = reverse('employee-attendance-detail', kwargs={'user_id': self.staff_user.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data.get('data', response.data)
        summary = data.get('summary', {})
        self.assertEqual(summary.get('absent_count'), 0)
        self.assertEqual(summary.get('present_count'), 1)

    @patch('auditlog.blob_service.download_log_file', return_value=None)
    @patch('auditlog.blob_service.upload_log_file', return_value=True)
    def test_employee_scan_checkin_clears_existing_absent_record(self, mock_upload, mock_download):
        """
        When staff checks in via /api/v1/attendance/employee/scan/, any existing absent record
        for today is purged, leaving only the newly created check-in session.
        """
        EmployeeAttendanceRecord.objects.create(
            user=self.staff_user,
            branch=self.branch,
            date=self.today,
            status='absent'
        )
        self.assertEqual(EmployeeAttendanceRecord.objects.filter(user=self.staff_user, date=self.today).count(), 1)

        self.client.force_authenticate(user=self.staff_user)
        url = reverse('employee-attendance-scan')
        response = self.client.post(url, {
            'scan_type': 'check_in',
            'latitude': 12.9716,
            'longitude': 77.5946
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Verify absent record was purged and only check-in record remains
        records = EmployeeAttendanceRecord.objects.filter(user=self.staff_user, date=self.today)
        self.assertEqual(records.count(), 1)
        self.assertEqual(records.first().status, 'checkout_pending')

    def test_auto_mark_staff_absentees_eod_does_not_mark_checked_in_staff(self):
        """
        EOD auto-mark absent task must not create an absent record for staff who already checked in.
        """
        EmployeeAttendanceRecord.objects.create(
            user=self.staff_user,
            branch=self.branch,
            date=self.today,
            status='present',
            checked_in_at=timezone.now(),
            checked_out_at=timezone.now()
        )

        auto_mark_staff_absentees_eod(target_date=self.today)

        # Staff user should still have only 1 record (present)
        self.assertEqual(
            EmployeeAttendanceRecord.objects.filter(user=self.staff_user, date=self.today).count(),
            1
        )
        self.assertEqual(
            EmployeeAttendanceRecord.objects.filter(user=self.staff_user, date=self.today).first().status,
            'present'
        )

        # Absent staff who never checked in should now have 1 absent record
        self.assertEqual(
            EmployeeAttendanceRecord.objects.filter(user=self.absent_staff, date=self.today, status='absent').count(),
            1
        )
