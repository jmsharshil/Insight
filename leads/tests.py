from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from auth_user.models import Organization, User
from leads.models import Lead
from leads.views import LeadListView


class BranchlessContactLeadVisibilityTests(TestCase):
    def test_branchless_contact_lead_is_visible_to_organization_admin(self):
        organization = Organization.objects.create(name='Test Organization')
        admin = User.objects.create_user(
            username='lead-admin',
            email='lead-admin@example.com',
            password='password',
            role='super_admin',
            organization=organization,
        )
        Lead.objects.create(
            form_type='contact',
            first_name='Public Contact',
            phone_student='33333',
            course='cseet',
            consent=True,
            branch=None,
        )
        request = APIRequestFactory().get('/api/v1/leads/')
        force_authenticate(request, user=admin)

        response = LeadListView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        names = [lead['first_name'] for lead in response.data['data']]
        self.assertIn('Public Contact', names)
