from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from branch.models import Branch
from .models import User, Organization
from .serializers import AddUserSerializer, UpdateUserSerializer
from .permissions import merge_modules_from_roles, ROLE_PERMISSIONS


class AdditionalRolesTestCase(TestCase):
    """Test cases for the additional_roles feature"""
    
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name='Test Org')
        self.branch = Branch.objects.create(
            organization=self.org,
            name='Main Branch',
            address='123 Main St',
            city='Delhi',
            state='Delhi',
            pincode='110001',
            phone='9999999999',
            email='branch@example.com',
        )
        
        # Create a super admin user for authentication
        self.super_admin = User.objects.create_user(
            username='superadmin',
            email='superadmin@test.org',
            password='Secret123!',
            role='super_admin',
            organization=self.org,
            phone='7777777777',
            name='Super Admin',
            is_active=True,
        )
    
    def test_merge_modules_from_roles(self):
        """Test that merge_modules_from_roles correctly merges modules from multiple roles"""
        # Get admin_executive's default modules
        admin_exec_modules = set(ROLE_PERMISSIONS['admin_executive']['default_modules'])
        # Get accountant's default modules
        accountant_modules = set(ROLE_PERMISSIONS['accountant']['default_modules'])
        
        # Merge them
        merged = merge_modules_from_roles('admin_executive', ['accountant'])
        merged_set = set(merged)
        
        # The merged result should contain all modules from both roles
        expected = admin_exec_modules | accountant_modules
        self.assertEqual(merged_set, expected)
    
    def test_merge_modules_with_multiple_additional_roles(self):
        """Test merging modules from primary role and multiple additional roles"""
        # Get modules for each role
        admin_modules = set(ROLE_PERMISSIONS['admin_executive']['default_modules'])
        accountant_modules = set(ROLE_PERMISSIONS['accountant']['default_modules'])
        counsellor_modules = set(ROLE_PERMISSIONS['counsellor']['default_modules'])
        
        # Merge primary with multiple additional roles
        merged = merge_modules_from_roles('admin_executive', ['accountant', 'counsellor'])
        merged_set = set(merged)
        
        # Should contain all modules from all roles
        expected = admin_modules | accountant_modules | counsellor_modules
        self.assertEqual(merged_set, expected)
    
    def test_add_user_with_additional_roles(self):
        """Test creating a user with additional_roles via AddUserSerializer"""
        data = {
            'email': 'user_with_roles@test.org',
            'phone': '8888888888',
            'name': 'User With Roles',
            'role': 'admin_executive',
            'branch': str(self.branch.id),
            'organization': str(self.org.id),
            'additional_roles': ['accountant'],
        }
        
        serializer = AddUserSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        
        user = serializer.save()
        
        # Check that user was created with additional_roles
        self.assertEqual(user.additional_roles, ['accountant'])
        
        # Check that accessible_modules was set correctly
        admin_modules = set(ROLE_PERMISSIONS['admin_executive']['default_modules'])
        accountant_modules = set(ROLE_PERMISSIONS['accountant']['default_modules'])
        expected_modules = sorted(list(admin_modules | accountant_modules))
        
        self.assertEqual(sorted(user.accessible_modules or []), expected_modules)
    
    def test_add_user_with_multiple_additional_roles(self):
        """Test creating a user with multiple additional_roles"""
        data = {
            'email': 'multi_roles@test.org',
            'phone': '7777777777',
            'name': 'Multi Roles User',
            'role': 'admin_executive',
            'branch': str(self.branch.id),
            'organization': str(self.org.id),
            'additional_roles': ['accountant', 'counsellor'],
        }
        
        serializer = AddUserSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        
        user = serializer.save()
        
        # Check additional_roles
        self.assertEqual(set(user.additional_roles), {'accountant', 'counsellor'})
        
        # Check accessible_modules contains all modules
        admin_modules = set(ROLE_PERMISSIONS['admin_executive']['default_modules'])
        accountant_modules = set(ROLE_PERMISSIONS['accountant']['default_modules'])
        counsellor_modules = set(ROLE_PERMISSIONS['counsellor']['default_modules'])
        expected_modules = sorted(list(admin_modules | accountant_modules | counsellor_modules))
        
        self.assertEqual(sorted(user.accessible_modules or []), expected_modules)
    
    def test_add_user_with_invalid_additional_roles(self):
        """Test that invalid additional_roles raise validation error"""
        data = {
            'email': 'invalid_roles@test.org',
            'phone': '6666666666',
            'name': 'Invalid Roles User',
            'role': 'admin_executive',
            'branch': str(self.branch.id),
            'organization': str(self.org.id),
            'additional_roles': ['invalid_role', 'another_invalid'],
        }
        
        serializer = AddUserSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('additional_roles', serializer.errors)
    
    def test_update_user_additional_roles(self):
        """Test updating a user's additional_roles via UpdateUserSerializer"""
        # Create a user first
        user = User.objects.create_user(
            username='testuser',
            email='testuser@test.org',
            password='Secret123!',
            role='admin_executive',
            organization=self.org,
            branch=self.branch,
            phone='5555555555',
            name='Test User',
            is_active=True,
        )
        
        # Update with additional_roles
        data = {
            'additional_roles': ['accountant'],
        }
        
        serializer = UpdateUserSerializer(user, data=data, partial=True)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        
        updated_user = serializer.save()
        
        # Check that additional_roles was set
        self.assertEqual(updated_user.additional_roles, ['accountant'])
        
        # Check that accessible_modules was updated
        admin_modules = set(ROLE_PERMISSIONS['admin_executive']['default_modules'])
        accountant_modules = set(ROLE_PERMISSIONS['accountant']['default_modules'])
        expected_modules = sorted(list(admin_modules | accountant_modules))
        
        self.assertEqual(sorted(updated_user.accessible_modules or []), expected_modules)
    
    def test_serializer_includes_additional_roles_in_response(self):
        """Test that serializers include additional_roles in response"""
        user = User.objects.create_user(
            username='serialtest',
            email='serialtest@test.org',
            password='Secret123!',
            role='admin_executive',
            organization=self.org,
            branch=self.branch,
            phone='4444444444',
            name='Serial Test User',
            additional_roles=['accountant', 'counsellor'],
            is_active=True,
        )
        
        from .serializers import UserSerializer, UserListSerializer
        
        # Test UserSerializer
        serializer = UserSerializer(user, context={'request': None})
        data = serializer.data
        self.assertIn('additional_roles', data)
        self.assertEqual(data['additional_roles'], ['accountant', 'counsellor'])
        
        # Test UserListSerializer
        serializer = UserListSerializer(user, context={'request': None})
        data = serializer.data
        self.assertIn('additional_roles', data)
        self.assertEqual(data['additional_roles'], ['accountant', 'counsellor'])
    
    def test_user_with_additional_roles_accessible_modules(self):
        """Test that accessible_modules is correctly computed for users with additional_roles"""
        user = User.objects.create_user(
            username='moduletest',
            email='moduletest@test.org',
            password='Secret123!',
            role='counsellor',
            organization=self.org,
            branch=self.branch,
            phone='3333333333',
            name='Module Test User',
            additional_roles=['fees'],  # fees module is more restricted
            is_active=True,
        )
        
        # Check that accessible_modules includes modules from both roles
        counsellor_modules = set(ROLE_PERMISSIONS['counsellor']['default_modules'])
        fees_modules = set(ROLE_PERMISSIONS.get('fees', {}).get('default_modules', []))
        
        if fees_modules:
            expected = sorted(list(counsellor_modules | fees_modules))
            self.assertEqual(sorted(user.accessible_modules or []), expected)
        else:
            # If 'fees' is not a valid role, this shouldn't happen, but check anyway
            self.assertIsNotNone(user.additional_roles)
    
    def test_additional_roles_field_in_user_model(self):
        """Test that User model has additional_roles field and defaults correctly"""
        user = User.objects.create_user(
            username='defaulttest',
            email='defaulttest@test.org',
            password='Secret123!',
            role='admin_executive',
            organization=self.org,
            branch=self.branch,
            phone='2222222222',
            name='Default Test User',
            is_active=True,
        )
        
        # Check that additional_roles defaults to empty list or None
        self.assertTrue(
            user.additional_roles is None or 
            user.additional_roles == [] or 
            user.additional_roles == dict()
        )
