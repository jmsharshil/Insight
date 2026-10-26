from unittest.mock import patch

from django.db.models import Model
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from auth_user.models import User
from branch.models import Branch
from payroll.models import LateEntryPolicy
from payroll.views import LatePolicyView


class LatePolicyBranchManagerAccessTest(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        with patch.object(
            Branch,
            'save',
            autospec=True,
            side_effect=lambda instance, *args, **kwargs: Model.save(instance, *args, **kwargs),
        ):
            self.branch = Branch.objects.create(
                name='Ahmedabad',
                address='Test address',
                city='Ahmedabad',
                state='Gujarat',
                pincode='380001',
                phone='9876543210',
                email='ahmedabad@example.com',
            )
            self.other_branch = Branch.objects.create(
                name='Mumbai',
                address='Test address',
                city='Mumbai',
                state='Maharashtra',
                pincode='400001',
                phone='9876543211',
                email='mumbai@example.com',
            )

        self.branch_policy = LateEntryPolicy.objects.create(branch=self.branch)
        LateEntryPolicy.objects.create(branch=self.other_branch)
        self.branch_manager = User.objects.create_user(
            username='late_policy_branch_manager',
            email='late_policy_branch_manager@example.com',
            password='test-password',
            role='branch_manager',
            branch=self.branch,
        )

    def test_branch_manager_can_see_policy_for_assigned_branch(self):
        request = self.factory.get('/api/v1/payroll/late-policy/')
        force_authenticate(request, user=self.branch_manager)

        response = LatePolicyView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item['id'] for item in response.data['data']], [str(self.branch_policy.id)])

    def test_non_policy_role_cannot_view_late_policy(self):
        user = User.objects.create_user(
            username='late_policy_student',
            email='late_policy_student@example.com',
            password='test-password',
            role='student',
            branch=self.branch,
        )
        request = self.factory.get('/api/v1/payroll/late-policy/')
        force_authenticate(request, user=user)

        response = LatePolicyView.as_view()(request)

        self.assertEqual(response.status_code, 403)
