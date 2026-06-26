from django.test import TestCase
from unittest.mock import patch, MagicMock
from auditlog.tasks import flush_logs_to_blob
from datetime import datetime
from django.utils import timezone


class AuditLogFlushTests(TestCase):
    @patch("auditlog.tasks.AuditLog")
    def test_flush_logs_to_blob_no_logs(self, mock_audit_log):
        """Test that flush does nothing when no unflushed logs exist."""
        # Mock the full queryset chain; list() will evaluate to empty
        mock_sliced_qs = []
        mock_order_by = MagicMock()
        mock_order_by.__getitem__.return_value = mock_sliced_qs
        mock_select = MagicMock()
        mock_select.order_by.return_value = mock_order_by
        mock_filter = MagicMock()
        mock_filter.select_related.return_value = mock_select
        mock_audit_log.objects.filter.return_value = mock_filter

        flush_logs_to_blob()

        mock_audit_log.objects.filter.assert_called_once_with(flushed_to_blob=False)
        mock_filter.select_related.assert_called_once_with("user", "organization")
        mock_order_by.__getitem__.assert_called_once_with(slice(None, 500))

    @patch("auditlog.tasks.upload_log_file")
    @patch("auditlog.tasks.AuditLog")
    def test_flush_logs_to_blob_exception(self, mock_audit_log, mock_upload):
        """Test exception handling during flush."""
        mock_audit_log.objects.filter.side_effect = Exception("Database error")

        with self.assertLogs("auditlog.tasks", level="ERROR") as log_cm:
            flush_logs_to_blob()

        self.assertTrue(
            any("Error during flush: Database error" in msg for msg in log_cm.output)
        )

    @patch("auditlog.tasks.upload_log_file")
    @patch("auditlog.tasks.AuditLog")
    def test_flush_logs_to_blob_success(self, mock_audit_log, mock_upload_log_file):
        """Test successful flush with realistic mocks, grouping, and bulk update."""
        now = timezone.now()
        mock_org = MagicMock()
        mock_org.name = "TestOrg"
        mock_user = MagicMock()
        mock_user.name = "Test User"
        mock_user.email = "test@example.com"
        mock_user.role = "admin"
        mock_user.id = 42

        mock_log1 = MagicMock(
            id=1,
            flushed_to_blob=False,
            timestamp=now,
            organization=mock_org,
            user=mock_user,
            user_id=42,
            organization_id=1,
            action="CREATE",
            method="POST",
            path="/api/v1/exams/1/schedule/",
            endpoint_name="exam-schedule",
            status_code=200,
            query_params="",
            request_body="{}",
            response_summary='{"success": "bool"}',
            ip_address="127.0.0.1",
            user_agent="Mozilla/5.0",
            target_model="",
            target_id="",
        )
        mock_log2 = MagicMock(
            id=2,
            flushed_to_blob=False,
            timestamp=now,
            organization=mock_org,
            user=mock_user,
            user_id=42,
            organization_id=1,
            action="CREATE",
            method="POST",
            path="/api/v1/exams/1/submit/",
            endpoint_name="exam-submit",
            status_code=200,
            query_params="",
            request_body='{"session_id": 99}',
            response_summary='{"submitted": "bool"}',
            ip_address="127.0.0.1",
            user_agent="Mozilla/5.0",
            target_model="",
            target_id="",
        )

        # Mock the queryset chain properly (filter -> select_related -> order_by -> slice)
        mock_sliced_qs = [mock_log1, mock_log2]
        mock_order_by = MagicMock()
        mock_order_by.__getitem__.return_value = mock_sliced_qs  # for [:BATCH_SIZE]
        mock_select = MagicMock()
        mock_select.order_by.return_value = mock_order_by
        mock_filter = MagicMock()
        mock_filter.select_related.return_value = mock_select
        mock_audit_log.objects.filter.return_value = mock_filter

        mock_upload_log_file.return_value = True

        flush_logs_to_blob()

        # Verify query for unflushed logs
        mock_audit_log.objects.filter.assert_any_call(flushed_to_blob=False)
        mock_filter.select_related.assert_called_once_with("user", "organization")
        mock_order_by.__getitem__.assert_called_once_with(slice(None, 500))

        # Verify upload called (with grouped data - note: defaultdict groups into 1 call here)
        self.assertEqual(mock_upload_log_file.call_count, 1)
        args, _ = mock_upload_log_file.call_args
        self.assertEqual(args[0], "TestOrg")  # organization_name
        self.assertEqual(args[1], "Test User")  # user_name
        self.assertEqual(len(args[3]), 2)  # 2 log entries in list

        # Verify mark-as-flushed (second filter + update)
        mock_audit_log.objects.filter.assert_any_call(id__in=[1, 2])
        # Since filter mock is reused, check that update was called
        mock_audit_log.objects.filter.return_value.update.assert_called_once_with(
            flushed_to_blob=True
        )
