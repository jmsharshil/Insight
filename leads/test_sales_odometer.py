import datetime
from decimal import Decimal
from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from rest_framework import status

from auth_user.models import User, Organization, NotificationHistory
from branch.models import Branch
from leads.models import SalesDailyActivity, SalesActivityPhoto, OdometerReading
from payroll.models import PayrollRun, PaySlip
from payroll.utils import _get_odometer_expenses_for_user

# Valid 1x1 GIF for testing ImageField uploads
TINY_GIF = (
    b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff'
    b'\x00\x00\x00\x21\xf9\x04\x01\x00\x00\x00\x00\x2c\x00\x00\x00\x00'
    b'\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00\x3b'
)


def sync_thread(target=None, args=(), kwargs=None, **other):
    """Run thread target synchronously in tests to avoid SQLite db locking."""
    class DummyThread:
        def start(self):
            if target:
                target(*args, **(kwargs or {}))
    return DummyThread()


class SalesActivityAndOdometerTests(TestCase):
    def setUp(self):
        # Patch threading.Thread to run synchronously for notifications
        self.thread_patcher = patch('threading.Thread', side_effect=sync_thread)
        self.thread_patcher.start()

        # Mock Azure blob service to avoid external calls in tests
        self.blob_upload_patcher = patch('auditlog.blob_service.upload_log_file', return_value=True)
        self.blob_upload_patcher.start()
        self.blob_download_patcher = patch('auditlog.blob_service.download_log_file', return_value="")
        self.blob_download_patcher.start()

        self.client = APIClient()
        self.org = Organization.objects.create(name="Test Org Sales")
        self.branch = Branch.objects.create(
            name="Main Branch",
            organization=self.org,
            latitude=12.9716,
            longitude=77.5946,
            allowed_radius_meters=1000
        )

        self.admin = User.objects.create_user(
            username="super_admin_sales",
            email="admin_sales@test.com",
            password="password123",
            role="super_admin",
            organization=self.org,
            branch=self.branch,
            name="Super Admin Sales",
            is_active=True
        )

        self.sales_user1 = User.objects.create_user(
            username="sales_rep_1",
            email="sales1@test.com",
            password="password123",
            role="sales_executive",
            organization=self.org,
            branch=self.branch,
            name="Alice Sales",
            is_active=True
        )

        self.sales_user2 = User.objects.create_user(
            username="sales_rep_2",
            email="sales2@test.com",
            password="password123",
            role="sales_executive",
            organization=self.org,
            branch=self.branch,
            name="Bob Sales",
            is_active=True
        )

        NotificationHistory.objects.all().delete()

    def tearDown(self):
        self.thread_patcher.stop()
        self.blob_upload_patcher.stop()
        self.blob_download_patcher.stop()

    def test_sales_activity_date_and_search_filters(self):
        """Test name search, date filter, and that empty result is returned for a date with no activity."""
        today = timezone.localdate()
        yesterday = today - datetime.timedelta(days=1)

        # Alice had activity yesterday
        act_alice_yesterday = SalesDailyActivity.objects.create(
            user=self.sales_user1,
            activity_date=yesterday,
            notes="Alice yesterday activity"
        )
        # Bob has activity today
        act_bob_today = SalesDailyActivity.objects.create(
            user=self.sales_user2,
            activity_date=today,
            notes="Bob today activity"
        )

        self.client.force_authenticate(user=self.admin)

        # 1. Search by name
        res = self.client.get('/api/v1/sales/activities/?search=Alice')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data), 1)
        self.assertEqual(res.data[0]['id'], str(act_alice_yesterday.id))

        # 2. Filter by date: yesterday
        res = self.client.get(f'/api/v1/sales/activities/?date={yesterday.isoformat()}')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data), 1)
        self.assertEqual(res.data[0]['id'], str(act_alice_yesterday.id))

        # 3. Filter by date: today
        res = self.client.get('/api/v1/sales/activities/?date=today')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data), 1)
        self.assertEqual(res.data[0]['id'], str(act_bob_today.id))

        # 4. Authenticate as Alice: Alice calls ?date=today (she has NO activity today yet)
        self.client.force_authenticate(user=self.sales_user1)
        res = self.client.get('/api/v1/sales/activities/?date=today')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        # Should be empty! Frontend can render empty upload fields.
        self.assertEqual(len(res.data), 0)

        # Alice calls without date filter: returns her past activity (yesterday)
        res = self.client.get('/api/v1/sales/activities/')
        self.assertEqual(len(res.data), 1)
        self.assertEqual(res.data[0]['activity_date'], str(yesterday))

    def test_odometer_photo_auto_creates_reading(self):
        """Test uploading start and end odometer photos auto-creates/updates OdometerReading."""
        today = timezone.localdate()
        activity = SalesDailyActivity.objects.create(
            user=self.sales_user1,
            activity_date=today,
            notes="Field visit"
        )

        self.client.force_authenticate(user=self.sales_user1)
        dummy_img = SimpleUploadedFile("start.gif", TINY_GIF, content_type="image/gif")

        # 1. Upload start odometer photo (100.5 km)
        res = self.client.post(
            f'/api/v1/sales/activities/{activity.id}/photos/',
            data={
                'photo_type': 'start_odometer',
                'photo': dummy_img,
                'latitude': '12.9716',
                'longitude': '77.5946',
                'odometer_kms': '100.50'
            },
            format='multipart'
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        reading = OdometerReading.objects.get(activity=activity)
        self.assertEqual(reading.start_kms, Decimal('100.50'))
        self.assertIsNone(reading.end_kms)
        self.assertEqual(reading.total_kms, Decimal('0.00'))
        self.assertEqual(reading.status, 'pending')

        # 2. Upload end odometer photo (155.5 km)
        dummy_img2 = SimpleUploadedFile("end.gif", TINY_GIF, content_type="image/gif")
        res = self.client.post(
            f'/api/v1/sales/activities/{activity.id}/photos/',
            data={
                'photo_type': 'end_odometer',
                'photo': dummy_img2,
                'latitude': '12.9716',
                'longitude': '77.5946',
                'odometer_kms': '155.50'
            },
            format='multipart'
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        reading.refresh_from_db()
        self.assertEqual(reading.end_kms, Decimal('155.50'))
        self.assertEqual(reading.total_kms, Decimal('55.00'))  # 155.50 - 100.50

        # Verify notification sent to admin with notification_type='sales'
        admin_notif = NotificationHistory.objects.filter(user=self.admin, notification_type='sales').first()
        self.assertIsNotNone(admin_notif)
        self.assertIn('55.0', admin_notif.body)

    def test_odometer_approve_and_reject_flow(self):
        """Test approving with editable expense_per_km and rejecting with reason."""
        today = timezone.localdate()
        activity = SalesDailyActivity.objects.create(
            user=self.sales_user1,
            activity_date=today
        )
        reading = OdometerReading.objects.create(
            activity=activity,
            user=self.sales_user1,
            start_kms=Decimal('100.00'),
            end_kms=Decimal('160.00'),
        )
        self.assertEqual(reading.total_kms, Decimal('60.00'))

        # 1. Staff cannot approve
        self.client.force_authenticate(user=self.sales_user1)
        res = self.client.post(
            f'/api/v1/sales/odometer-readings/{reading.id}/approve/',
            data={'expense_per_km': '5.00'},
            format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # 2. Admin approves with expense_per_km = 6.50
        self.client.force_authenticate(user=self.admin)
        res = self.client.post(
            f'/api/v1/sales/odometer-readings/{reading.id}/approve/',
            data={'expense_per_km': '6.50'},
            format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data['success'])

        reading.refresh_from_db()
        self.assertEqual(reading.status, 'approved')
        self.assertEqual(reading.expense_per_km, Decimal('6.50'))
        self.assertEqual(reading.total_expense, Decimal('390.00'))  # 60 * 6.50
        self.assertEqual(reading.approved_by, self.admin)

        # Check in-app notification sent to Alice with type='sales'
        user_notif = NotificationHistory.objects.filter(user=self.sales_user1, notification_type='sales').first()
        self.assertIsNotNone(user_notif)
        self.assertEqual(user_notif.notification_type, 'sales')
        self.assertIn('Approved', user_notif.title)
        self.assertIn('390.00', user_notif.body)

        # 3. Reject flow on a second reading
        activity2 = SalesDailyActivity.objects.create(
            user=self.sales_user2,
            activity_date=today
        )
        reading2 = OdometerReading.objects.create(
            activity=activity2,
            user=self.sales_user2,
            start_kms=Decimal('50.00'),
            end_kms=Decimal('80.00'),
        )
        res = self.client.post(
            f'/api/v1/sales/odometer-readings/{reading2.id}/reject/',
            data={'rejection_reason': 'Invalid odometer picture'},
            format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        reading2.refresh_from_db()
        self.assertEqual(reading2.status, 'rejected')
        self.assertEqual(reading2.rejection_reason, 'Invalid odometer picture')

        # Check notification sent to Bob with type='sales'
        bob_notif = NotificationHistory.objects.filter(user=self.sales_user2, notification_type='sales').first()
        self.assertIsNotNone(bob_notif)
        self.assertEqual(bob_notif.notification_type, 'sales')
        self.assertIn('Rejected', bob_notif.title)
        self.assertIn('Invalid odometer picture', bob_notif.body)

    def test_payroll_payslip_integration(self):
        """Test that approved odometer reading amount is fetched and added to payslip."""
        today = timezone.localdate()
        activity = SalesDailyActivity.objects.create(
            user=self.sales_user1,
            activity_date=today
        )
        reading = OdometerReading.objects.create(
            activity=activity,
            user=self.sales_user1,
            start_kms=Decimal('100.00'),
            end_kms=Decimal('150.00'),
            expense_per_km=Decimal('5.00'),
            status='approved',
            is_paid=False
        )
        self.assertEqual(reading.total_expense, Decimal('250.00'))

        payroll_run = PayrollRun.objects.create(
            month=today.month,
            year=today.year,
            branch=self.branch,
            status='draft'
        )

        # Test helper function
        readings_qs, total_amount = _get_odometer_expenses_for_user(self.sales_user1, payroll_run)
        self.assertEqual(total_amount, Decimal('250.00'))
        self.assertEqual(readings_qs.count(), 1)

    def test_notification_history_sales_filter(self):
        """Test GET /api/auth/notifications/?type=sales."""
        NotificationHistory.objects.all().delete()
        NotificationHistory.objects.create(
            user=self.sales_user1,
            title="Sales Notification",
            body="Your odometer was approved",
            notification_type="sales",
            data={"odometer_reading_id": "some-id"}
        )
        NotificationHistory.objects.create(
            user=self.sales_user1,
            title="Attendance Notification",
            body="Check in recorded",
            notification_type="attendance"
        )

        self.client.force_authenticate(user=self.sales_user1)
        res = self.client.get('/api/auth/notifications/?type=sales')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        items = res.data.get('data', [])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['notification_type'], 'sales')
