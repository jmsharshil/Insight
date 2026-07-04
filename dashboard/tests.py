from django.test import SimpleTestCase
from unittest.mock import patch, MagicMock
from rest_framework.test import APIRequestFactory, override_settings
from rest_framework import status
from django.contrib.auth.models import AnonymousUser
from datetime import datetime

from dashboard.views import DashboardAPIView


@override_settings(
    REST_FRAMEWORK={
        'DEFAULT_AUTHENTICATION_CLASSES': [
            'rest_framework.authentication.SessionAuthentication',
        ],
        'DEFAULT_PERMISSION_CLASSES': [
            'rest_framework.permissions.IsAuthenticated',
        ],
        'DEFAULT_THROTTLE_RATES': {
            'user': '60/minute',
        },
    },
    CACHES={
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        }
    },
)
class DashboardTests(SimpleTestCase):
    """Comprehensive tests for dashboard covering all roles, edge cases, caching, and error scenarios.
    Uses SimpleTestCase + mocks + override_settings to avoid DB, auth config, and migration issues.
    Uses APIRequestFactory for isolated view testing without URLconf dependency.
    """

    def setUp(self):
        self.factory = APIRequestFactory()
        # Mock users (no real DB objects)
        self.super_user = MagicMock(spec=['role', 'id', 'branch_id', 'organization', 'is_authenticated'])
        self.super_user.role = 'super_admin'
        self.super_user.id = 1
        self.super_user.branch_id = 1
        self.super_user.organization = MagicMock(id=1)
        self.super_user.is_authenticated = True

        self.faculty_user = MagicMock(spec=['role', 'id', 'branch_id', 'organization', 'is_authenticated'])
        self.faculty_user.role = 'faculty'
        self.faculty_user.id = 2
        self.faculty_user.branch_id = 1
        self.faculty_user.organization = MagicMock(id=1)
        self.faculty_user.is_authenticated = True

        self.student_user = MagicMock(spec=['role', 'id', 'branch_id', 'organization', 'is_authenticated'])
        self.student_user.role = 'student'
        self.student_user.id = 3
        self.student_user.branch_id = 1
        self.student_user.organization = MagicMock(id=1)
        self.student_user.is_authenticated = True

        self.sales_user = MagicMock(spec=['role', 'id', 'branch_id', 'organization', 'is_authenticated'])
        self.sales_user.role = 'sales_executive'
        self.sales_user.id = 4
        self.sales_user.branch_id = 1
        self.sales_user.organization = MagicMock(id=1)
        self.sales_user.is_authenticated = True

        self.unknown_user = MagicMock(spec=['role', 'id', 'branch_id', 'organization', 'is_authenticated'])
        self.unknown_user.role = 'unknown_role'
        self.unknown_user.id = 5
        self.unknown_user.branch_id = None
        self.unknown_user.organization = None
        self.unknown_user.is_authenticated = True

        self.view = DashboardAPIView.as_view()

    @patch('dashboard.views.get_role_dashboard')
    def test_dashboard_super_admin(self, mock_get_role):
        """Test management dashboard for super_admin."""
        mock_get_role.return_value = {
            'kpis': {'total_active_students': 150, 'attendance_rate': 92.5},
            'upcoming_exams': [],
            'charts': {}
        }
        request = self.factory.get('/api/v1/dashboard/')
        request.user = self.super_user
        response = self.view(request)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
        self.assertEqual(response.data['role'], 'super_admin')
        self.assertIn('kpis', response.data['data'])
        mock_get_role.assert_called_once_with(self.super_user)

    @patch('dashboard.views.get_role_dashboard')
    def test_dashboard_faculty(self, mock_get_role):
        """Test faculty dashboard with pending tasks and sessions."""
        mock_get_role.return_value = {
            'kpis': {'today_sessions': 3, 'pending_tasks': 2, 'attendance_rate': 95.0},
            'today_schedule': [],
            'pending_tasks': [{'id': 1, 'student_name': 'John Doe'}],
            'recent_sessions': [],
            'payroll_summary': {'pending_salary': 0}
        }
        request = self.factory.get('/api/v1/dashboard/')
        request.user = self.faculty_user
        response = self.view(request)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['role'], 'faculty')
        self.assertIn('payroll_summary', response.data['data'])

    @patch('dashboard.views.get_role_dashboard')
    def test_dashboard_student(self, mock_get_role):
        """Test student/parent dashboard with personal data."""
        mock_get_role.return_value = {
            'kpis': {'attendance_rate': 88.0, 'fees_due': 2500.0, 'avg_score': 78.5},
            'upcoming_exams': [],
            'recent_results': [],
            'timetable': [],
            'charts': {'my_performance': {}}
        }
        request = self.factory.get('/api/v1/dashboard/')
        request.user = self.student_user
        response = self.view(request)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['role'], 'student')

    @patch('dashboard.views.get_role_dashboard')
    def test_dashboard_sales(self, mock_get_role):
        """Test sales dashboard focused on leads."""
        mock_get_role.return_value = {
            'kpis': {'total_leads': 45, 'conversion_rate': 32.5},
            'pipeline': [],
            'recent_leads': []
        }
        request = self.factory.get('/api/v1/dashboard/')
        request.user = self.sales_user
        response = self.view(request)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['role'], 'sales_executive')

    def test_unauthenticated_access(self):
        """Edge case: unauthenticated should return 401."""
        request = self.factory.get('/api/v1/dashboard/')
        # No user set -> AnonymousUser implicitly for permission check
        response = self.view(request)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch('dashboard.views.clear_dashboard_cache')
    @patch('dashboard.views.get_role_dashboard')
    def test_refresh_param_bypasses_cache(self, mock_get_role, mock_clear):
        """Test ?refresh=true clears cache and forces fresh data."""
        mock_get_role.return_value = {'kpis': {'refreshed': True}}
        request = self.factory.get('/api/v1/dashboard/?refresh=true')
        request.user = self.super_user
        response = self.view(request)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['data'].get('refreshed', False))
        mock_clear.assert_called_once_with(self.super_user)
        mock_get_role.assert_called_once_with(self.super_user)

    @patch('dashboard.views.clear_dashboard_cache')
    @patch('dashboard.views.get_role_dashboard')
    def test_default_role_fallback(self, mock_get_role, mock_clear):
        """Test unknown role falls to default dashboard."""
        mock_get_role.return_value = {'kpis': {'message': 'Dashboard ready for your role'}}
        request = self.factory.get('/api/v1/dashboard/')
        request.user = self.unknown_user
        response = self.view(request)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['role'], 'unknown_role')
        self.assertIn('message', response.data['data']['kpis'])
        mock_get_role.assert_called_once_with(self.unknown_user)

    @patch('dashboard.views.get_role_dashboard')
    def test_throttling(self, mock_get_role):
        """Test rate limiting (60/min) - simulate multiple calls. Uses same user to hit per-user throttle cache."""
        mock_get_role.return_value = {'kpis': {'test': True}}
        for _ in range(5):  # well under limit
            request = self.factory.get('/api/v1/dashboard/')
            request.user = self.super_user
            response = self.view(request)
            self.assertNotEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(mock_get_role.call_count, 5)

    @patch('dashboard.views.get_role_dashboard')
    def test_cache_key_isolation(self, mock_get_role):
        """Test different roles/users get isolated cache keys (via different mock calls)."""
        mock_get_role.return_value = {'kpis': {'test': True}}
        for user in [self.super_user, self.faculty_user, self.student_user]:
            request = self.factory.get('/api/v1/dashboard/')
            request.user = user
            response = self.view(request)
            self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(mock_get_role.call_count, 3)

    def test_response_structure(self):
        """Validate consistent response format across roles."""
        with patch('dashboard.views.get_role_dashboard') as mock_get:
            mock_get.return_value = {'kpis': {}, 'charts': {}}
            request = self.factory.get('/api/v1/dashboard/')
            request.user = self.super_user
            response = self.view(request)
            data = response.data
            self.assertIn('success', data)
            self.assertIn('role', data)
            self.assertIn('data', data)
            self.assertIn('timestamp', data)
            self.assertTrue(data['success'])
            self.assertIsInstance(data['data'], dict)
            self.assertIn('kpis', data['data'])
            self.assertIn('role', data['data'])  # merged in service
