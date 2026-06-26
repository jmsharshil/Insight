from django.test import TestCase
from unittest.mock import patch, MagicMock
from auditlog.tasks import flush_logs_to_blob
from datetime import datetime
from django.utils import timezone

class AuditLogFlushTests(TestCase):
    @patch('auditlog.models.AuditLog')
    def test_flush_logs_to_blob_no_logs(self, mock_audit_log):
        # Setup mock to return no unflushed logs
        mock_audit_log.objects.filter.return_value.select_related.return_value.order_by.return_value = []

        flush_logs_to_blob()

        # Assertions
        mock_audit_log.objects.filter.assert_called_once_with(flushed_to_blob=False)
    
    @patch('auditlog.blob_service.upload_log_file')
    @patch('auditlog.models.AuditLog')
    def test_flush_logs_to_blob_exception(self, mock_audit_log, mock_upload_log_file):
        # Setup mock to raise exception on query
        mock_audit_log.objects.filter.side_effect = Exception("Database error")

        with self.assertLogs('auditlog.tasks', level='ERROR') as log_cm:
            flush_logs_to_blob()
            self.assertTrue(any("Error during flush: Database error" in msg for msg in log_cm.output))

    @patch('auditlog.blob_service.upload_log_file')
    @patch('auditlog.models.AuditLog')
    def test_flush_logs_to_blob_success(self, mock_audit_log, mock_upload_log_file):
        # Setup realistic mock logs
        now = timezone.now()
        mock_org = MagicMock()
        mock_org.name = 'Org1'
        mock_user = MagicMock()
        mock_user.name = 'User 1'
        mock_user.email = 'user1@test.com'
        mock_user.role = 'admin'
        mock_user.id = 100

        mock_log1 = MagicMock(
            id=1,
            flushed_to_blob=False,
            timestamp=now,
            organization=mock_org,
            user=mock_user,
            user_id=100,
            organization_id=10,
            action='CREATE',
            method='POST',
            path='/api/test/',
            endpoint_name='test',
            status_code=201,
            query_params='',
            request_body='{}',
            response_summary='success',
            ip_address='127.0.0.1',
            user_agent='test-agent',
            target_model='',
            target_id='',
        )
        mock_log2 = MagicMock(
            id=2,
            flushed_to_blob=False,
            timestamp=now,
            organization=mock_org,
            user=mock_user,
            user_id=100,
            organization_id=10,
            action='READ',
            method='GET',
            path='/api/test/',
            endpoint_name='test',
            status_code=200,
            query_params='',
            request_body='',
            response_summary='',
            ip_address='127.0.0.1',
            user_agent='test-agent',
            target_model='',
            target_id='',
        )

        mock_audit_log.objects.filter.return_value.select_related.return_value.order_by.return_value = [mock_log1, mock_log2]
        mock_upload_log_file.return_value = True
        
        flush_logs_to_blob()

        # Assertions
        mock_upload_log_file.assert_called_once()
        # Note: update is called on a separate filter(id__in=...) but since mock shares return_value, it works
        mock_audit_log.objects.filter.return_value.update.assert_called_once_with(flushed_to_blob=True)
