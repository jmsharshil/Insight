import uuid
from decimal import Decimal
from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from rest_framework import status

from reimbursements.models import Reimbursement
from reimbursements.utils import (
    handle_reimbursement_whatsapp_approval,
    send_reimbursement_whatsapp_notification,
    is_super_admin_user,
    is_accountant_user,
)
from branch.models import Branch
from auth_user.models import Organization

User = get_user_model()


class ReimbursementTwoLevelApprovalTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name="Insight Org")
        self.branch = Branch.objects.create(name="Main Branch", organization=self.org)

        # Staff claimant
        self.claimant = User.objects.create_user(
            username="employee1",
            email="employee1@test.com",
            password="password123",
            role="counsellor",
            phone="919876543210",
            name="Alice Staff",
            organization=self.org,
            branch=self.branch,
            is_active=True,
        )

        # Accountant (Level 1 approver)
        self.accountant = User.objects.create_user(
            username="accountant1",
            email="accountant1@test.com",
            password="password123",
            role="accountant",
            phone="919876543211",
            name="Bob Accountant",
            organization=self.org,
            branch=self.branch,
            is_active=True,
        )

        # Super Admin (Level 2 / Direct approver)
        self.super_admin = User.objects.create_user(
            username="superadmin1",
            email="superadmin1@test.com",
            password="password123",
            role="super_admin",
            phone="919876543212",
            name="Charlie SuperAdmin",
            organization=self.org,
            is_active=True,
        )

        self.dummy_proof = SimpleUploadedFile("bill.pdf", b"%PDF-1.4 dummy", content_type="application/pdf")

    @patch("chat.notifications.send_whatsapp_with_fallback")
    @patch("chat.notifications.send_system_notification")
    def test_claim_submission_notifies_both_accountant_and_super_admin_simultaneously(self, mock_sys_notif, mock_wa):
        """When user applies for reimbursement, both accountant and super admin receive WhatsApp msg at the same time."""
        self.client.force_authenticate(user=self.claimant)
        response = self.client.post(
            "/api/v1/reimbursements/",
            {
                "title": "Seminar Expenses",
                "description": "Purchased notebooks and pens",
                "amount": "1500.00",
                "expense_date": str(timezone.now().date()),
                "proof": self.dummy_proof,
            },
            format="multipart"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        claim_data = response.data["data"]
        self.assertEqual(claim_data["status"], "pending")

        # Verify WhatsApp was sent to BOTH accountant and super admin
        wa_phones_sent = [call.kwargs.get("to") for call in mock_wa.call_args_list]
        self.assertIn(self.accountant.phone, wa_phones_sent)
        self.assertIn(self.super_admin.phone, wa_phones_sent)

        # Verify quick-reply buttons are present
        for call in mock_wa.call_args_list:
            self.assertEqual(call.kwargs.get("template_name"), "reimbursement_claim_")
            components = call.kwargs.get("components", [])
            button_components = [c for c in components if c.get("type") == "button"]
            self.assertEqual(len(button_components), 2)
            self.assertIn(f"reimb_approve:{claim_data['id']}", button_components[0]["parameters"][0]["payload"])

    @patch("chat.notifications.send_whatsapp_with_fallback")
    @patch("chat.notifications.send_system_notification")
    def test_super_admin_approves_directly_without_accountant(self, mock_sys_notif, mock_wa):
        """If super admin approves first, claim is approved directly without needing accountant approval."""
        reimb = Reimbursement.objects.create(
            user=self.claimant,
            branch=self.branch,
            title="Flight Ticket",
            amount=Decimal("3500.00"),
            proof=self.dummy_proof,
            status="pending"
        )

        self.client.force_authenticate(user=self.super_admin)
        response = self.client.post(f"/api/v1/reimbursements/{reimb.id}/approve/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        reimb.refresh_from_db()
        self.assertEqual(reimb.status, "approved")
        self.assertEqual(reimb.approved_by, self.super_admin)
        self.assertIsNone(reimb.accountant_approved_by)

        # If accountant attempts to approve now, it is already approved
        self.client.force_authenticate(user=self.accountant)
        acc_response = self.client.post(f"/api/v1/reimbursements/{reimb.id}/approve/")
        self.assertEqual(acc_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("already approved", acc_response.data["message"].lower())

    @patch("chat.notifications.send_whatsapp_with_fallback")
    @patch("chat.notifications.send_system_notification")
    def test_accountant_approves_first_requires_super_admin_approval(self, mock_sys_notif, mock_wa):
        """If accountant approves first, claim moves to approved_by_accountant and requires super admin approval."""
        reimb = Reimbursement.objects.create(
            user=self.claimant,
            branch=self.branch,
            title="Office Snacks",
            amount=Decimal("800.00"),
            proof=self.dummy_proof,
            status="pending"
        )

        # Accountant approves (Level 1)
        self.client.force_authenticate(user=self.accountant)
        response = self.client.post(f"/api/v1/reimbursements/{reimb.id}/approve/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("approved by Accountant", response.data["message"])

        reimb.refresh_from_db()
        self.assertEqual(reimb.status, "approved_by_accountant")
        self.assertEqual(reimb.accountant_approved_by, self.accountant)
        self.assertIsNotNone(reimb.accountant_approved_at)
        self.assertIsNone(reimb.approved_by)

        # Super Admin received alert to approve
        wa_recipients = [call.kwargs.get("to") for call in mock_wa.call_args_list]
        self.assertIn(self.super_admin.phone, wa_recipients)

        # Accountant tries to approve again -> should indicate waiting for super admin
        acc_repeat_response = self.client.post(f"/api/v1/reimbursements/{reimb.id}/approve/")
        self.assertEqual(acc_repeat_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("awaiting final approval from Super Admin", acc_repeat_response.data["message"])

        # Super admin approves (Level 2 final approval)
        self.client.force_authenticate(user=self.super_admin)
        sa_response = self.client.post(f"/api/v1/reimbursements/{reimb.id}/approve/")
        self.assertEqual(sa_response.status_code, status.HTTP_200_OK)

        reimb.refresh_from_db()
        self.assertEqual(reimb.status, "approved")
        self.assertEqual(reimb.approved_by, self.super_admin)
        self.assertEqual(reimb.accountant_approved_by, self.accountant)

    @patch("chat.notifications.send_whatsapp_text")
    @patch("chat.notifications.send_whatsapp_with_fallback")
    @patch("chat.notifications.send_system_notification")
    def test_whatsapp_super_admin_direct_approval(self, mock_sys_notif, mock_wa_fb, mock_wa_text):
        """Super Admin approves directly via WhatsApp quick reply from 'pending'."""
        reimb = Reimbursement.objects.create(
            user=self.claimant,
            branch=self.branch,
            title="Travel Fare",
            amount=Decimal("1200.00"),
            proof=self.dummy_proof,
            status="pending"
        )

        handled = handle_reimbursement_whatsapp_approval(
            sender_wa_id=self.super_admin.phone,
            payload_str=f"reimb_approve:{reimb.id}",
            text_str="Approve"
        )
        self.assertTrue(handled)

        reimb.refresh_from_db()
        self.assertEqual(reimb.status, "approved")
        self.assertEqual(reimb.approved_by, self.super_admin)

        # Super Admin received confirmation WhatsApp text
        mock_wa_text.assert_called()
        self.assertIn("APPROVED", mock_wa_text.call_args_list[0].kwargs.get("body", ""))

    @patch("chat.notifications.send_whatsapp_text")
    @patch("chat.notifications.send_whatsapp_with_fallback")
    @patch("chat.notifications.send_system_notification")
    def test_whatsapp_two_level_approval_flow(self, mock_sys_notif, mock_wa_fb, mock_wa_text):
        """Accountant approves via WhatsApp -> approved_by_accountant, then Super Admin approves -> approved."""
        reimb = Reimbursement.objects.create(
            user=self.claimant,
            branch=self.branch,
            title="Courier Charges",
            amount=Decimal("250.00"),
            proof=self.dummy_proof,
            status="pending"
        )

        # 1. Accountant clicks Approve on WhatsApp
        handled = handle_reimbursement_whatsapp_approval(
            sender_wa_id=self.accountant.phone,
            payload_str=f"reimb_approve:{reimb.id}",
            text_str="Approve"
        )
        self.assertTrue(handled)

        reimb.refresh_from_db()
        self.assertEqual(reimb.status, "approved_by_accountant")
        self.assertEqual(reimb.accountant_approved_by, self.accountant)
        self.assertIsNone(reimb.approved_by)

        # Accountant received text stating pending Super Admin approval
        self.assertIn("pending final approval from Super Admin", mock_wa_text.call_args_list[0].kwargs.get("body", ""))

        # 2. Super Admin clicks Approve on WhatsApp
        handled_sa = handle_reimbursement_whatsapp_approval(
            sender_wa_id=self.super_admin.phone,
            payload_str=f"reimb_approve:{reimb.id}",
            text_str="Approve"
        )
        self.assertTrue(handled_sa)

        reimb.refresh_from_db()
        self.assertEqual(reimb.status, "approved")
        self.assertEqual(reimb.approved_by, self.super_admin)

    @patch("chat.notifications.send_whatsapp_text")
    @patch("chat.notifications.send_system_notification")
    def test_whatsapp_rejection_logic(self, mock_sys_notif, mock_wa_text):
        """Accountant cannot reject a claim once it is in approved_by_accountant; Super Admin can."""
        reimb = Reimbursement.objects.create(
            user=self.claimant,
            branch=self.branch,
            title="Lunch Meeting",
            amount=Decimal("500.00"),
            proof=self.dummy_proof,
            status="approved_by_accountant",
            accountant_approved_by=self.accountant,
            accountant_approved_at=timezone.now()
        )

        # Accountant tries to reject
        handled = handle_reimbursement_whatsapp_approval(
            sender_wa_id=self.accountant.phone,
            payload_str=f"reimb_reject:{reimb.id}",
            text_str="Reject"
        )
        self.assertTrue(handled)
        reimb.refresh_from_db()
        self.assertEqual(reimb.status, "approved_by_accountant")
        self.assertIn("Only Super Admin can reject it", mock_wa_text.call_args_list[-1].kwargs.get("body", ""))

        # Super Admin rejects
        handled_sa = handle_reimbursement_whatsapp_approval(
            sender_wa_id=self.super_admin.phone,
            payload_str=f"reimb_reject:{reimb.id}",
            text_str="Reject"
        )
        self.assertTrue(handled_sa)
        reimb.refresh_from_db()
        self.assertEqual(reimb.status, "rejected")
        self.assertEqual(reimb.rejected_by, self.super_admin)

    def test_self_approval_disallowed(self):
        """Approvers cannot approve their own claims."""
        reimb = Reimbursement.objects.create(
            user=self.super_admin,
            branch=self.branch,
            title="Admin Expense",
            amount=Decimal("1000.00"),
            proof=self.dummy_proof,
            status="pending"
        )

        self.client.force_authenticate(user=self.super_admin)
        response = self.client.post(f"/api/v1/reimbursements/{reimb.id}/approve/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("cannot approve your own", response.data["message"].lower())
