import uuid
from decimal import Decimal
from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

from leads.models import SalesDailyActivity, SalesActivityPhoto, SalesAttendanceApproval
from leads.utils import (
    get_sales_attendance_approvers,
    send_sales_attendance_approval_requests,
    apply_sales_attendance_approval,
    apply_sales_attendance_rejection,
    parse_sales_attendance_payload,
    handle_sales_attendance_whatsapp_approval,
)
from attendance.models import EmployeeAttendanceRecord
from branch.models import Branch
from auth_user.models import Organization

User = get_user_model()


class SalesAttendanceApprovalTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Insight Org")
        self.branch = Branch.objects.create(name="Main Branch", organization=self.org)

        # Salesperson
        self.sales_user = User.objects.create_user(
            username="salesperson1",
            email="sales1@example.com",
            password="password123",
            role="sales_executive",
            phone="919876543210",
            name="John Sales",
            organization=self.org,
            branch=self.branch,
            is_active=True,
        )

        # CMO
        self.cmo_user = User.objects.create_user(
            username="cmo_user",
            email="cmo@example.com",
            password="password123",
            role="cmo",
            phone="919876543211",
            name="Alice CMO",
            organization=self.org,
            is_active=True,
        )

        # Super Admin
        self.sa_user = User.objects.create_user(
            username="sa_user",
            email="sa@example.com",
            password="password123",
            role="super_admin",
            phone="919876543212",
            name="Bob SuperAdmin",
            organization=self.org,
            is_active=True,
        )

        self.today = timezone.localdate()
        self.activity = SalesDailyActivity.objects.create(
            user=self.sales_user,
            activity_date=self.today,
            name="Daily Field Operations",
        )

        dummy_img = SimpleUploadedFile("selfie.jpg", b"dummy image content", content_type="image/jpeg")
        self.start_photo = SalesActivityPhoto.objects.create(
            activity=self.activity,
            photo_type="start_selfie",
            photo=dummy_img,
            latitude=Decimal("23.022500"),
            longitude=Decimal("72.571400"),
            captured_at=timezone.now(),
        )

    def test_get_sales_attendance_approvers(self):
        approvers = get_sales_attendance_approvers(self.sales_user)
        approver_ids = {u.id for u in approvers}
        self.assertIn(self.cmo_user.id, approver_ids)
        self.assertIn(self.sa_user.id, approver_ids)
        self.assertNotIn(self.sales_user.id, approver_ids)

    @patch("chat.notifications.send_whatsapp_with_fallback")
    @patch("chat.notifications.send_system_notification")
    def test_send_sales_attendance_approval_requests(self, mock_system_notif, mock_whatsapp):
        approval = SalesAttendanceApproval.objects.create(
            user=self.sales_user,
            activity=self.activity,
            photo=self.start_photo,
            approval_type="check_in",
            date=self.today,
            captured_at=self.start_photo.captured_at,
            latitude=self.start_photo.latitude,
            longitude=self.start_photo.longitude,
            status="pending",
        )

        send_sales_attendance_approval_requests(approval)
        self.assertEqual(mock_whatsapp.call_count, 2)
        self.assertEqual(mock_system_notif.call_count, 2)

        first_call_kwargs = mock_whatsapp.call_args_list[0].kwargs
        self.assertEqual(first_call_kwargs.get("template_name"), "sales_attendance_approval_")
        components = first_call_kwargs.get("components", [])

        # Verify header has the selfie image link
        header = components[0]
        self.assertEqual(header["type"], "header")
        self.assertIn("selfie", header["parameters"][0]["image"]["link"])

        # Verify body has 5 parameters
        body = components[1]
        self.assertEqual(body["type"], "body")
        self.assertEqual(len(body["parameters"]), 5)

    def test_apply_sales_attendance_approval_check_in(self):
        approval = SalesAttendanceApproval.objects.create(
            user=self.sales_user,
            activity=self.activity,
            photo=self.start_photo,
            approval_type="check_in",
            date=self.today,
            captured_at=self.start_photo.captured_at,
            latitude=self.start_photo.latitude,
            longitude=self.start_photo.longitude,
            status="pending",
        )

        # Before approval: no EmployeeAttendanceRecord exists
        self.assertFalse(EmployeeAttendanceRecord.objects.filter(user=self.sales_user, date=self.today).exists())

        # CMO approves
        with patch("chat.notifications.send_whatsapp_text"), patch("chat.notifications.send_system_notification"):
            success, msg = apply_sales_attendance_approval(approval, self.cmo_user)

        self.assertTrue(success)
        approval.refresh_from_db()
        self.assertEqual(approval.status, "approved")
        self.assertEqual(approval.approved_by, self.cmo_user)
        self.assertIsNotNone(approval.attendance_record)

        # After approval: entry has arrived!
        record = EmployeeAttendanceRecord.objects.get(user=self.sales_user, date=self.today)
        self.assertEqual(record.status, "checkout_pending")
        self.assertEqual(record.check_in_method, "selfie")
        self.assertEqual(record.latitude, self.start_photo.latitude)

    def test_apply_sales_attendance_approval_check_out(self):
        # First create check-in record (9.5 hours ago to satisfy 9-hour requirement)
        checkin_time = timezone.now() - timezone.timedelta(hours=9, minutes=30)
        record = EmployeeAttendanceRecord.objects.create(
            user=self.sales_user,
            branch=self.branch,
            date=self.today,
            status="checkout_pending",
            checked_in_at=checkin_time,
            check_in_method="selfie",
        )

        dummy_img = SimpleUploadedFile("end_selfie.jpg", b"end image content", content_type="image/jpeg")
        end_photo = SalesActivityPhoto.objects.create(
            activity=self.activity,
            photo_type="end_selfie",
            photo=dummy_img,
            latitude=Decimal("23.022500"),
            longitude=Decimal("72.571400"),
            captured_at=timezone.now(),
        )

        approval = SalesAttendanceApproval.objects.create(
            user=self.sales_user,
            activity=self.activity,
            photo=end_photo,
            approval_type="check_out",
            date=self.today,
            captured_at=end_photo.captured_at,
            latitude=end_photo.latitude,
            longitude=end_photo.longitude,
            status="pending",
        )

        # Super Admin approves
        with patch("chat.notifications.send_whatsapp_text"), patch("chat.notifications.send_system_notification"):
            success, msg = apply_sales_attendance_approval(approval, self.sa_user)

        self.assertTrue(success)
        approval.refresh_from_db()
        self.assertEqual(approval.status, "approved")
        self.assertEqual(approval.approved_by, self.sa_user)

        record.refresh_from_db()
        self.assertEqual(record.status, "present")
        self.assertEqual(record.check_out_method, "selfie")
        self.assertIsNotNone(record.checked_out_at)

    def test_apply_sales_attendance_rejection(self):
        approval = SalesAttendanceApproval.objects.create(
            user=self.sales_user,
            activity=self.activity,
            photo=self.start_photo,
            approval_type="check_in",
            date=self.today,
            captured_at=self.start_photo.captured_at,
            latitude=self.start_photo.latitude,
            longitude=self.start_photo.longitude,
            status="pending",
        )

        with patch("chat.notifications.send_whatsapp_text"), patch("chat.notifications.send_system_notification"):
            success, msg = apply_sales_attendance_rejection(approval, self.cmo_user, reason="Selfie blurry")

        self.assertTrue(success)
        approval.refresh_from_db()
        self.assertEqual(approval.status, "rejected")
        self.assertEqual(approval.rejected_by, self.cmo_user)
        self.assertEqual(approval.rejection_reason, "Selfie blurry")

        # No attendance record created
        self.assertFalse(EmployeeAttendanceRecord.objects.filter(user=self.sales_user, date=self.today).exists())

    def test_parse_sales_attendance_payload(self):
        sample_uuid = str(uuid.uuid4())
        # Quick reply payload
        action, aid = parse_sales_attendance_payload(f"sales_att_approve:{sample_uuid}")
        self.assertEqual(action, "approve")
        self.assertEqual(aid, sample_uuid)

        action, aid = parse_sales_attendance_payload(f"sales_att_reject:{sample_uuid}")
        self.assertEqual(action, "reject")
        self.assertEqual(aid, sample_uuid)

        # Text reply
        action, aid = parse_sales_attendance_payload("", f"approve sales {sample_uuid}")
        self.assertEqual(action, "approve")
        self.assertEqual(aid, sample_uuid)

    @patch("chat.notifications.send_whatsapp_text")
    @patch("chat.notifications.send_system_notification")
    def test_handle_sales_attendance_whatsapp_approval(self, mock_system_notif, mock_send_wa):
        approval = SalesAttendanceApproval.objects.create(
            user=self.sales_user,
            activity=self.activity,
            photo=self.start_photo,
            approval_type="check_in",
            date=self.today,
            captured_at=self.start_photo.captured_at,
            latitude=self.start_photo.latitude,
            longitude=self.start_photo.longitude,
            status="pending",
        )

        # CMO clicks "Approve" via WhatsApp
        handled = handle_sales_attendance_whatsapp_approval(
            sender_wa_id="919876543211",
            payload_str=f"sales_att_approve:{approval.id}",
            text_str="Approve"
        )
        self.assertTrue(handled)
        approval.refresh_from_db()
        self.assertEqual(approval.status, "approved")
        self.assertEqual(approval.approved_by, self.cmo_user)

        # Second approval by Super Admin is gracefully handled (already approved)
        handled_second = handle_sales_attendance_whatsapp_approval(
            sender_wa_id="919876543212",
            payload_str=f"sales_att_approve:{approval.id}",
            text_str="Approve"
        )
        self.assertTrue(handled_second)


class SalesAttendanceApprovalAPITests(TestCase):
    def setUp(self):
        from rest_framework.test import APIClient
        self.client = APIClient()

        self.org = Organization.objects.create(name="Insight Org")
        self.branch = Branch.objects.create(name="Main Branch", organization=self.org)

        self.sales_user = User.objects.create_user(
            username="salesperson_api",
            email="salesapi@example.com",
            password="password123",
            role="sales_executive",
            phone="919876543220",
            name="John Sales API",
            organization=self.org,
            branch=self.branch,
            is_active=True,
        )

        self.cmo_user = User.objects.create_user(
            username="cmo_api",
            email="cmoapi@example.com",
            password="password123",
            role="cmo",
            phone="919876543221",
            name="Alice CMO API",
            organization=self.org,
            is_active=True,
        )

        self.today = timezone.localdate()
        self.activity = SalesDailyActivity.objects.create(
            user=self.sales_user,
            activity_date=self.today,
            name="Daily Field Operations",
        )

        dummy_img = SimpleUploadedFile("selfie.jpg", b"image bytes", content_type="image/jpeg")
        self.photo = SalesActivityPhoto.objects.create(
            activity=self.activity,
            photo_type="start_selfie",
            photo=dummy_img,
            latitude=Decimal("23.022500"),
            longitude=Decimal("72.571400"),
            captured_at=timezone.now(),
        )

        self.approval = SalesAttendanceApproval.objects.create(
            user=self.sales_user,
            activity=self.activity,
            photo=self.photo,
            approval_type="check_in",
            date=self.today,
            captured_at=self.photo.captured_at,
            latitude=self.photo.latitude,
            longitude=self.photo.longitude,
            status="pending",
        )

    def test_list_approvals_as_cmo(self):
        self.client.force_authenticate(user=self.cmo_user)
        response = self.client.get("/api/v1/sales/attendance-approvals/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["id"], str(self.approval.id))

    def test_approve_via_api(self):
        self.client.force_authenticate(user=self.cmo_user)
        with patch("chat.notifications.send_whatsapp_text"), patch("chat.notifications.send_system_notification"):
            response = self.client.post(f"/api/v1/sales/attendance-approvals/{self.approval.id}/approve/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])

        self.approval.refresh_from_db()
        self.assertEqual(self.approval.status, "approved")
        self.assertEqual(self.approval.approved_by, self.cmo_user)
        self.assertTrue(EmployeeAttendanceRecord.objects.filter(user=self.sales_user, date=self.today).exists())

    def test_reject_via_api(self):
        self.client.force_authenticate(user=self.cmo_user)
        with patch("chat.notifications.send_whatsapp_text"), patch("chat.notifications.send_system_notification"):
            response = self.client.post(
                f"/api/v1/sales/attendance-approvals/{self.approval.id}/reject/",
                data={"reason": "Location not matching scheduled plan"}
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])

        self.approval.refresh_from_db()
        self.assertEqual(self.approval.status, "rejected")
        self.assertEqual(self.approval.rejected_by, self.cmo_user)
        self.assertEqual(self.approval.rejection_reason, "Location not matching scheduled plan")
        self.assertFalse(EmployeeAttendanceRecord.objects.filter(user=self.sales_user, date=self.today).exists())


