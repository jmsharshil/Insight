from unittest.mock import patch

from django.db.models import Model
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from auth_user.models import Organization, User
from branch.models import Branch
from faculty.models import FacultyProfile
from faculty.views import FacultyListCreateView


class BranchManagerFacultyVisibilityTest(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        manager_organization = Organization.objects.create(name='Manager Organization')
        branch_organization = Organization.objects.create(name='Branch Organization')

        with patch.object(
            Branch,
            'save',
            autospec=True,
            side_effect=lambda instance, *args, **kwargs: Model.save(instance, *args, **kwargs),
        ):
            self.assigned_branch = Branch.objects.create(
                name='Assigned Branch',
                organization=branch_organization,
                address='Test address',
                city='Ahmedabad',
                state='Gujarat',
                pincode='380001',
                phone='9876543210',
                email='assigned@example.com',
            )
            other_branch = Branch.objects.create(
                name='Other Branch',
                organization=manager_organization,
                address='Test address',
                city='Mumbai',
                state='Maharashtra',
                pincode='400001',
                phone='9876543211',
                email='other@example.com',
            )

        self.manager = User.objects.create_user(
            username='faculty_branch_manager',
            email='faculty_branch_manager@example.com',
            password='test-password',
            name='Branch Manager',
            role='branch_manager',
            branch=self.assigned_branch,
            organization=manager_organization,
        )
        assigned_faculty_user = User.objects.create_user(
            username='assigned_faculty',
            email='assigned_faculty@example.com',
            password='test-password',
            name='Assigned Faculty',
            role='faculty',
        )
        other_faculty_user = User.objects.create_user(
            username='other_faculty',
            email='other_faculty@example.com',
            password='test-password',
            name='Other Faculty',
            role='faculty',
        )
        self.assigned_faculty = FacultyProfile.objects.create(
            user=assigned_faculty_user,
            branch=self.assigned_branch,
            qualification='Test qualification',
            specialization='Test specialization',
            joining_date='2026-01-01',
        )
        FacultyProfile.objects.create(
            user=other_faculty_user,
            branch=other_branch,
            qualification='Test qualification',
            specialization='Test specialization',
            joining_date='2026-01-01',
        )

    def test_branch_manager_sees_faculty_from_assigned_branch(self):
        request = self.factory.get('/api/v1/faculty/')
        force_authenticate(request, user=self.manager)

        response = FacultyListCreateView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(
            [str(item['id']) for item in response.data['data']],
            [str(self.assigned_faculty.id)],
        )
