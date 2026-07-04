from unittest.mock import patch

from django.test import SimpleTestCase

from auditlog.tasks import cleanup_old_audit_logs
from auth_user.tasks import cleanup_old_notifications


class RetentionCleanupTests(SimpleTestCase):
    @patch("auditlog.tasks.AuditLog.objects.filter")
    def test_cleanup_old_audit_logs_deletes_rows_older_than_retention(self, filter_mock):
        filter_mock.return_value.delete.return_value = (3, {})

        deleted = cleanup_old_audit_logs(retention_days=21)

        self.assertEqual(deleted, 3)
        filter_mock.assert_called_once()
        filter_mock.return_value.delete.assert_called_once()

    @patch("auth_user.tasks.NotificationHistory.objects.filter")
    def test_cleanup_old_notifications_deletes_rows_older_than_retention(self, filter_mock):
        filter_mock.return_value.delete.return_value = (5, {})

        deleted = cleanup_old_notifications(retention_days=21)

        self.assertEqual(deleted, 5)
        filter_mock.assert_called_once()
        filter_mock.return_value.delete.assert_called_once()
