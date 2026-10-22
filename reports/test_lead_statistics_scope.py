from django.db.models import Model
from django.test import TestCase
from django.utils import timezone
from unittest.mock import patch

from auth_user.models import Organization, User
from branch.models import Branch
from dashboard.services import _get_management_dashboard
from leads.models import Lead
from reports.services.leads import get_lead_report


class SuperAdminLeadStatisticsScopeTest(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name='Lead Statistics Organization')
        other_organization = Organization.objects.create(name='Other Organization')

        with patch.object(
            Branch,
            'save',
            autospec=True,
            side_effect=lambda instance, *args, **kwargs: Model.save(instance, *args, **kwargs),
        ):
            self.organization_branch = Branch.objects.create(
                name='Organization Branch',
                organization=self.organization,
                address='Test address',
                city='Ahmedabad',
                state='Gujarat',
                pincode='380001',
                phone='9876543210',
                email='org-branch@example.com',
            )
            other_branch = Branch.objects.create(
                name='Other Organization Branch',
                organization=other_organization,
                address='Test address',
                city='Mumbai',
                state='Maharashtra',
                pincode='400001',
                phone='9876543211',
                email='other-branch@example.com',
            )

        self.super_admin = User.objects.create_user(
            username='lead_statistics_super_admin',
            email='lead_statistics_super_admin@example.com',
            password='test-password',
            name='Super Admin',
            role='super_admin',
            organization=self.organization,
        )

        self._create_lead('Organization lead', branch=self.organization_branch)
        self._create_lead('Unassigned lead', branch=None)
        self._create_lead('Other organization lead', branch=other_branch)

    @staticmethod
    def _create_lead(name, branch):
        return Lead.objects.create(
            branch=branch,
            form_type='inquiry',
            first_name=name,
            phone_student='9876543210',
            current_stage='new',
        )

    def test_report_counts_match_visible_leads_including_unassigned(self):
        report = get_lead_report(self.super_admin, {})

        self.assertEqual(report['total_leads'], 2)
        self.assertEqual(report['new'], 2)
        self.assertEqual(sum(item['count'] for item in report['by_source']), 2)

    @patch('dashboard.services._get_enrollment_by_course', return_value=[])
    @patch('dashboard.services._get_attendance_by_batch', return_value=[])
    @patch('dashboard.services._get_recent_activities', return_value=[])
    @patch('dashboard.services._get_fee_trend', return_value=[])
    @patch('dashboard.services._get_attendance_trend', return_value=[])
    @patch('dashboard.services._get_result_delay_stats', return_value={})
    @patch('dashboard.services._get_exam_stats', return_value={})
    def test_dashboard_lead_counts_match_visible_leads(
        self,
        mock_exam_stats,
        mock_result_delay_stats,
        mock_attendance_trend,
        mock_fee_trend,
        mock_recent_activities,
        mock_attendance_by_batch,
        mock_enrollment_by_course,
    ):
        now = timezone.now()
        dashboard = _get_management_dashboard(
            self.super_admin,
            now,
            now.date(),
            now.replace(day=1, hour=0, minute=0, second=0, microsecond=0),
            now - timezone.timedelta(days=30),
        )

        self.assertEqual(dashboard['kpis']['open_leads'], 2)
        self.assertEqual(sum(item['count'] for item in dashboard['lead_pipeline']), 2)
