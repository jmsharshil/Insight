from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient
from django.core import mail

from .models import User, Organization, PasswordSetToken


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class AuthUserAPITestCase(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_create_organization_and_super_admin(self):
        url = reverse('create-organization')
        payload = {
            'organization_name': 'Test Org',
            'username': 'superadmin',
            'email': 'superadmin@test.org',
            'phone': '9999999999',
            'name': 'Super Admin',
        }

        response = self.client.post(url, payload, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertIn('organization_id', response.data)
        self.assertIn('user_id', response.data)

        organization = Organization.objects.get(id=response.data['organization_id'])
        user = User.objects.get(id=response.data['user_id'])

        self.assertEqual(organization.name, 'Test Org')
        self.assertEqual(user.role, 'super_admin')
        self.assertEqual(user.organization, organization)
        self.assertFalse(user.is_active)

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Set your Insight ERP password', mail.outbox[0].subject)
        self.assertIn(user.email, mail.outbox[0].to)

        token = PasswordSetToken.objects.filter(user=user, is_used=False).last()
        self.assertIsNotNone(token)
        self.assertIn(token.token, mail.outbox[0].body)

    def test_password_set_endpoint_activates_user(self):
        org = Organization.objects.create(name='Test Org 2')
        user = User.objects.create_user(
            username='superadmin2',
            email='superadmin2@test.org',
            password=None,
            role='super_admin',
            organization=org,
            phone='8888888888',
            name='Super Admin 2',
            is_active=False,
        )
        token = PasswordSetToken.objects.create(user=user, token='test-token')

        url = reverse('set-password')
        payload = {
            'token': token.token,
            'password': 'NewPass123',
            'confirm_password': 'NewPass123',
        }

        response = self.client.post(url, payload, format='json')
        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        token.refresh_from_db()

        self.assertTrue(user.is_active)
        self.assertTrue(user.check_password('NewPass123'))
        self.assertTrue(token.is_used)

    def test_super_admin_can_add_user_to_organization(self):
        org = Organization.objects.create(name='Super Org')
        super_admin = User.objects.create_user(
            username='superadmin3',
            email='superadmin3@test.org',
            password='Secret123!',
            role='super_admin',
            organization=org,
            phone='7777777777',
            name='Super Admin 3',
            is_active=True,
        )

        login_url = reverse('login')
        login_response = self.client.post(
            login_url,
            {'email': super_admin.email, 'password': 'Secret123!'},
            format='json',
        )
        self.assertEqual(login_response.status_code, 200)
        access_token = login_response.data['access']

        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access_token}')

        add_user_url = reverse('add-user')
        add_payload = {
            'username': 'newuser',
            'email': 'newuser@test.org',
            'phone': '6666666666',
            'name': 'New User',
            'role': 'admin_executive',
        }

        add_response = self.client.post(add_user_url, add_payload, format='json')
        self.assertEqual(add_response.status_code, 201)
        self.assertIn('user_id', add_response.data)

        created_user = User.objects.get(id=add_response.data['user_id'])
        self.assertEqual(created_user.organization, org)
        self.assertEqual(created_user.role, 'admin_executive')
        self.assertFalse(created_user.is_active)

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(created_user.email, mail.outbox[0].to)
