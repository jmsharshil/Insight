from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient
from django.core import mail

from branch.models import Branch
from .models import User, Organization, PasswordSetToken
from .serializers import AddUserSerializer, UpdateUserSerializer
from .utils import calculate_working_hours
from decimal import Decimal
from datetime import time


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
        self.assertIn('Set your Test Org password', mail.outbox[0].subject)
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

    def test_add_user_serializer_accepts_single_branch_string(self):
        org = Organization.objects.create(name='Single Branch Org')
        branch = Branch.objects.create(
            organization=org,
            name='Main Branch',
            address='123 Main St',
            city='Delhi',
            state='Delhi',
            pincode='110001',
            phone='9999999999',
            email='branch@example.com',
        )

        serializer = AddUserSerializer(data={
            'username': 'singlebranchuser',
            'email': 'singlebranchuser@test.org',
            'phone': '6666666666',
            'name': 'Single Branch User',
            'role': 'admin_executive',
            'organization': str(org.id),
            'branch': str(branch.id),
            'branches': str(branch.id),
        })

        self.assertTrue(serializer.is_valid(), serializer.errors)
        user = serializer.save()
        self.assertEqual(list(user.branches.values_list('id', flat=True)), [branch.id])

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

        self.client.force_authenticate(user=super_admin)

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

    def test_phone_number_must_be_unique_in_add_user(self):
        org = Organization.objects.create(name='Unique Phone Org')
        User.objects.create_user(
            username='user1',
            email='user1@test.org',
            password='Password123!',
            phone='9876543210',
            name='User One',
            organization=org,
        )

        serializer = AddUserSerializer(data={
            'email': 'user2@test.org',
            'phone': '9876543210',
            'name': 'User Two',
            'role': 'admin_executive',
            'organization': str(org.id),
        })
        self.assertFalse(serializer.is_valid())
        self.assertIn('phone', serializer.errors)

    def test_phone_number_must_be_unique_in_register(self):
        from .serializers import RegisterSerializer
        User.objects.create_user(
            username='existinguser',
            email='existing@test.org',
            password='Password123!',
            phone='9876543210',
            name='Existing User',
        )

        serializer = RegisterSerializer(data={
            'email': 'newstudent@test.org',
            'phone': '9876543210',
            'name': 'New Student',
            'password': 'Password123!',
            'role': 'student',
        })
        self.assertFalse(serializer.is_valid())
        self.assertIn('phone', serializer.errors)

    def test_phone_number_must_be_unique_in_organization_create(self):
        from .serializers import OrganizationCreateSerializer
        User.objects.create_user(
            username='existingadmin',
            email='existingadmin@test.org',
            password='Password123!',
            phone='9876543210',
            name='Existing Admin',
        )

        serializer = OrganizationCreateSerializer(data={
            'organization_name': 'New Org',
            'email': 'newadmin@test.org',
            'phone': '9876543210',
            'name': 'New Admin',
        })
        self.assertFalse(serializer.is_valid())
        self.assertIn('phone', serializer.errors)

    def test_phone_number_must_be_unique_in_update_user(self):
        from .serializers import UpdateUserSerializer
        org = Organization.objects.create(name='Update Phone Org')
        u1 = User.objects.create_user(
            username='update_u1',
            email='u1@test.org',
            password='Password123!',
            phone='9876543210',
            name='User One',
            organization=org,
        )
        u2 = User.objects.create_user(
            username='update_u2',
            email='u2@test.org',
            password='Password123!',
            phone='9876543211',
            name='User Two',
            organization=org,
        )

        # Trying to update u2's phone to u1's phone should fail
        serializer = UpdateUserSerializer(u2, data={'phone': '9876543210'}, partial=True)
        self.assertFalse(serializer.is_valid())
        self.assertIn('phone', serializer.errors)

        # Updating u2 with their own phone should succeed
        serializer_same = UpdateUserSerializer(u2, data={'phone': '9876543211', 'name': 'Updated Name'}, partial=True)
        self.assertTrue(serializer_same.is_valid(), serializer_same.errors)

    def test_phone_number_uniqueness_at_database_level(self):
        from django.db import IntegrityError
        User.objects.create_user(
            username='db_user1',
            email='db1@test.org',
            password='Password123!',
            phone='9876543210',
            name='DB User 1',
        )
        with self.assertRaises(IntegrityError):
            User.objects.create_user(
                username='db_user2',
                email='db2@test.org',
                password='Password123!',
                phone='9876543210',
                name='DB User 2',
            )

    def test_calculate_working_hours_function(self):
        # 09:00 to 17:00 -> 8 hours
        self.assertEqual(calculate_working_hours(time(9, 0), time(17, 0)), Decimal('8.00'))
        self.assertEqual(calculate_working_hours('09:00:00', '17:00:00'), Decimal('8.00'))
        # 09:30 to 18:00 -> 8.5 hours
        self.assertEqual(calculate_working_hours('09:30:00', '18:00:00'), Decimal('8.50'))
        # 09:00 to 17:45 -> 8.75 hours
        self.assertEqual(calculate_working_hours('09:00', '17:45'), Decimal('8.75'))
        # Overnight shift 22:00 to 06:00 -> 8 hours
        self.assertEqual(calculate_working_hours('22:00:00', '06:00:00'), Decimal('8.00'))
        # Same start and end -> 0 hours
        self.assertEqual(calculate_working_hours('09:00:00', '09:00:00'), Decimal('0.00'))
        # None inputs -> 0 hours
        self.assertEqual(calculate_working_hours(None, '17:00:00'), Decimal('0.00'))
        self.assertEqual(calculate_working_hours('09:00:00', None), Decimal('0.00'))

    def test_add_user_auto_calculates_working_hours_when_not_provided(self):
        org = Organization.objects.create(name='Work Hour Org')
        branch = Branch.objects.create(organization=org, name='Main Branch', address='123 St', phone='9876543210', email='b@test.org')
        serializer = AddUserSerializer(data={
            'email': 'counsellor_auto@test.org',
            'phone': '9111111111',
            'name': 'Counsellor Auto',
            'role': 'counsellor',
            'organization': str(org.id),
            'branch': str(branch.id),
            'work_start_time': '09:00:00',
            'work_end_time': '17:30:00',
        })
        self.assertTrue(serializer.is_valid(), serializer.errors)
        user = serializer.save()
        self.assertEqual(user.working_hours, Decimal('8.50'))

    def test_add_user_auto_calculates_working_hours_when_empty_or_zero(self):
        org = Organization.objects.create(name='Work Hour Org 2')
        branch = Branch.objects.create(organization=org, name='Main Branch', address='123 St', phone='9876543210', email='b2@test.org')
        serializer = AddUserSerializer(data={
            'email': 'counsellor_empty@test.org',
            'phone': '9111111112',
            'name': 'Counsellor Empty',
            'role': 'counsellor',
            'organization': str(org.id),
            'branch': str(branch.id),
            'work_start_time': '09:00:00',
            'work_end_time': '18:00:00',
            'working_hours': '',
        })
        self.assertTrue(serializer.is_valid(), serializer.errors)
        user = serializer.save()
        self.assertEqual(user.working_hours, Decimal('9.00'))

    def test_add_user_preserves_explicit_working_hours(self):
        org = Organization.objects.create(name='Work Hour Org 3')
        branch = Branch.objects.create(organization=org, name='Main Branch', address='123 St', phone='9876543210', email='b3@test.org')
        serializer = AddUserSerializer(data={
            'email': 'counsellor_custom@test.org',
            'phone': '9111111113',
            'name': 'Counsellor Custom',
            'role': 'counsellor',
            'organization': str(org.id),
            'branch': str(branch.id),
            'work_start_time': '09:00:00',
            'work_end_time': '18:00:00',
            'working_hours': '6.00',
        })
        self.assertTrue(serializer.is_valid(), serializer.errors)
        user = serializer.save()
        self.assertEqual(user.working_hours, Decimal('6.00'))

    def test_add_user_api_endpoint_calculates_working_hours(self):
        org = Organization.objects.create(name='Work Hour Org API')
        super_admin = User.objects.create_user(
            username='admin_wh',
            email='admin_wh@test.org',
            password='Secret123!',
            role='super_admin',
            organization=org,
            phone='9111111114',
            name='Super Admin WH',
            is_active=True,
        )
        self.client.force_authenticate(user=super_admin)

        add_user_url = reverse('add-user')
        add_payload = {
            'email': 'new_staff@test.org',
            'phone': '9111111115',
            'name': 'New Staff',
            'role': 'admin_executive',
            'work_start_time': '10:00:00',
            'work_end_time': '18:00:00',
        }

        response = self.client.post(add_user_url, add_payload, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data.get('working_hours'), '8.00')

        created_user = User.objects.get(id=response.data['user_id'])
        self.assertEqual(created_user.working_hours, Decimal('8.00'))

    def test_user_model_save_auto_calculates_working_hours(self):
        user = User.objects.create_user(
            username='direct_user',
            email='direct_user@test.org',
            password='Password123!',
            phone='9111111116',
            name='Direct User',
            role='faculty',
            work_start_time=time(9, 0),
            work_end_time=time(17, 0),
        )
        self.assertEqual(user.working_hours, Decimal('8.00'))

    def test_update_user_serializer_recalculates_working_hours_when_time_changes(self):
        org = Organization.objects.create(name='Work Hour Org Update')
        user = User.objects.create_user(
            username='update_wh_user',
            email='update_wh@test.org',
            password='Password123!',
            phone='9111111117',
            name='Update WH User',
            role='admin_executive',
            organization=org,
            work_start_time=time(9, 0),
            work_end_time=time(17, 0),
            working_hours=Decimal('8.00'),
        )
        serializer = UpdateUserSerializer(
            user,
            data={'work_end_time': '19:00:00'},
            partial=True
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        updated_user = serializer.save()
        self.assertEqual(updated_user.working_hours, Decimal('10.00'))

    def test_process_weekly_schedule_auto_calculates_each_day(self):
        from .utils import process_weekly_schedule
        sched = {
            'monday': {'start_time': '10:00:00', 'end_time': '19:00:00', 'is_off': False},
            'tuesday': {'start_time': '13:00:00', 'end_time': '19:00:00', 'is_off': False},
            'wednesday': {'start_time': '10:00:00', 'end_time': '20:00:00', 'working_hours': 10.0, 'is_off': False},
            'sunday': {'start_time': '10:00:00', 'end_time': '18:00:00', 'is_off': True},
        }
        processed, avg_hours = process_weekly_schedule(sched)
        self.assertEqual(processed['monday']['working_hours'], 9.0)
        self.assertEqual(processed['monday']['is_off'], False)
        self.assertEqual(processed['tuesday']['working_hours'], 6.0)
        self.assertEqual(processed['tuesday']['is_off'], False)
        self.assertEqual(processed['wednesday']['working_hours'], 10.0)
        self.assertEqual(processed['wednesday']['is_off'], False)
        # Sunday has start and end times, so working_hours is calculated as 8.0, and is_off is True
        self.assertEqual(processed['sunday']['working_hours'], 8.0)
        self.assertEqual(processed['sunday']['is_off'], True)
        self.assertEqual(processed['sunday']['start_time'], '10:00:00')
        self.assertEqual(processed['sunday']['end_time'], '18:00:00')
        # avg of non-off days (9, 6, 10) is 25 / 3 = 8.33
        self.assertEqual(avg_hours, Decimal('8.33'))

    def test_user_get_working_hours_for_date(self):
        from datetime import date
        user = User.objects.create_user(
            username='sched_user',
            email='sched_user@test.org',
            password='Password123!',
            phone='9111111118',
            name='Schedule User',
            role='admin_executive',
            weekly_schedule={
                'monday': {'start_time': '10:00:00', 'end_time': '19:00:00', 'is_off': False},
                'tuesday': {'start_time': '13:00:00', 'end_time': '19:00:00', 'is_off': False},
                'sunday': {'start_time': '10:00:00', 'end_time': '18:00:00', 'is_off': True},
            }
        )
        # Monday (2026-10-12 was Monday)
        monday_date = date(2026, 10, 12)
        self.assertEqual(monday_date.strftime('%A').lower(), 'monday')
        self.assertEqual(user.get_working_hours_for_date(monday_date), Decimal('9.00'))
        self.assertFalse(user.is_day_off(monday_date))

        # Tuesday (2026-10-13 was Tuesday)
        tuesday_date = date(2026, 10, 13)
        self.assertEqual(user.get_working_hours_for_date(tuesday_date), Decimal('6.00'))
        self.assertFalse(user.is_day_off(tuesday_date))

        # Sunday (2026-10-18 is Sunday) - is_off=True so required working hours is 0.00
        sunday_date = date(2026, 10, 18)
        self.assertEqual(user.get_working_hours_for_date(sunday_date), Decimal('0.00'))
        self.assertTrue(user.is_day_off(sunday_date))

        # Shift timings on Sunday still resolved
        sun_s, sun_e = user.get_shift_timings_for_date(sunday_date)
        self.assertEqual(sun_s, time(10, 0))
        self.assertEqual(sun_e, time(18, 0))

        # Shift timings on Monday
        mon_s, mon_e = user.get_shift_timings_for_date(monday_date)
        self.assertEqual(mon_s, time(10, 0))
        self.assertEqual(mon_e, time(19, 0))

    def test_payroll_does_not_deduct_for_is_off_day(self):
        from decimal import Decimal
        from datetime import date
        org = Organization.objects.create(name='Payroll Off Org')
        user = User.objects.create_user(
            username='payroll_off_user',
            email='payroll_off@test.org',
            password='Password123!',
            phone='9111111129',
            name='Payroll Off User',
            role='counsellor',
            salary=Decimal('30000.00'),
            employment_type='full_time',
            organization=org,
            weekly_schedule={
                'monday': {'start_time': '10:00:00', 'end_time': '19:00:00', 'is_off': False},
                'tuesday': {'start_time': '10:00:00', 'end_time': '19:00:00', 'is_off': False},
                'wednesday': {'start_time': '10:00:00', 'end_time': '19:00:00', 'is_off': True},
                'thursday': {'start_time': '10:00:00', 'end_time': '19:00:00', 'is_off': False},
                'friday': {'start_time': '10:00:00', 'end_time': '19:00:00', 'is_off': False},
                'saturday': {'start_time': '10:00:00', 'end_time': '14:00:00', 'is_off': False},
                'sunday': {'start_time': '10:00:00', 'end_time': '18:00:00', 'is_off': True},
            }
        )
        wednesday_date = date(2026, 5, 6) # Wednesday
        thursday_date = date(2026, 5, 7)  # Thursday
        self.assertTrue(user.is_day_off(wednesday_date))
        self.assertFalse(user.is_day_off(thursday_date))
        # Wednesday is an off day: required hours is 0
        self.assertEqual(user.get_working_hours_for_date(wednesday_date), Decimal('0.00'))
        # Thursday is a working day: required hours is 9.00
        self.assertEqual(user.get_working_hours_for_date(thursday_date), Decimal('9.00'))

    def test_add_user_with_weekly_schedule_calculates_daily_and_average_working_hours(self):
        org = Organization.objects.create(name='Weekly Sched Org')
        serializer = AddUserSerializer(data={
            'email': 'weekly_user@test.org',
            'phone': '9111111119',
            'name': 'Weekly User',
            'role': 'counsellor',
            'organization': str(org.id),
            'weekly_schedule': {
                'monday': {'start_time': '10:00:00', 'end_time': '19:00:00'},
                'tuesday': {'start_time': '13:00:00', 'end_time': '19:00:00'},
            }
        })
        self.assertTrue(serializer.is_valid(), serializer.errors)
        user = serializer.save()
        self.assertEqual(user.weekly_schedule['monday']['working_hours'], 9.0)
        self.assertEqual(user.weekly_schedule['tuesday']['working_hours'], 6.0)
        # Average of 9.0 and 6.0 = 7.50
        self.assertEqual(user.working_hours, Decimal('7.50'))

    def test_add_user_with_flat_day_fields(self):
        org = Organization.objects.create(name='Flat Day Org')
        serializer = AddUserSerializer(data={
            'email': 'flat_day_user@test.org',
            'phone': '9111111120',
            'name': 'Flat Day User',
            'role': 'counsellor',
            'organization': str(org.id),
            'monday_start_time': '10:00:00',
            'monday_end_time': '19:00:00',
            'tuesday_start_time': '13:00:00',
            'tuesday_end_time': '19:00:00',
        })
        self.assertTrue(serializer.is_valid(), serializer.errors)
        user = serializer.save()
        self.assertIn('monday', user.weekly_schedule)
        self.assertEqual(user.weekly_schedule['monday']['working_hours'], 9.0)
        self.assertEqual(user.weekly_schedule['tuesday']['working_hours'], 6.0)
        self.assertEqual(user.working_hours, Decimal('7.50'))

    def test_add_user_api_endpoint_with_weekly_schedule(self):
        org = Organization.objects.create(name='API Weekly Org')
        admin = User.objects.create_superuser(
            username='api_weekly_admin',
            email='api_weekly_admin@test.org',
            password='Password123!',
            organization=org,
            phone='9111111121',
        )
        self.client.force_authenticate(user=admin)
        url = reverse('add-user')
        payload = {
            'email': 'api_weekly_employee@test.org',
            'phone': '9111111122',
            'name': 'API Weekly Employee',
            'role': 'admin_executive',
            'organization': str(org.id),
            'weekly_schedule': {
                'monday': {'start_time': '10:00:00', 'end_time': '19:00:00'},
                'tuesday': {'start_time': '13:00:00', 'end_time': '19:00:00'},
            }
        }
        response = self.client.post(url, payload, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data.get('working_hours'), '7.50')
        self.assertIn('weekly_schedule', response.data)
        self.assertEqual(response.data['weekly_schedule']['monday']['working_hours'], 9.0)
        self.assertEqual(response.data['weekly_schedule']['tuesday']['working_hours'], 6.0)

    def test_sunday_start_and_end_time_with_is_off_and_working_hours(self):
        org = Organization.objects.create(name='Sunday Org')
        user = User.objects.create_user(
            username='sunday_worker',
            email='sunday@test.org',
            password='Password123!',
            phone='9111111123',
            name='Sunday Worker',
            role='counsellor',
            organization=org,
            weekly_schedule={
                'sunday': {'start_time': '10:00:00', 'end_time': '14:00:00', 'is_off': True},
                'monday': {'start_time': '09:00:00', 'end_time': '18:00:00', 'is_off': False},
            }
        )
        # Sunday has working_hours auto-calculated in schedule
        self.assertIn('sunday', user.weekly_schedule)
        self.assertEqual(user.weekly_schedule['sunday']['start_time'], '10:00:00')
        self.assertEqual(user.weekly_schedule['sunday']['end_time'], '14:00:00')
        self.assertEqual(user.weekly_schedule['sunday']['working_hours'], 4.0)
        self.assertTrue(user.weekly_schedule['sunday']['is_off'])

        # Since Sunday is is_off=True, user.working_hours average only counts active days (Monday: 9.00)
        self.assertEqual(user.working_hours, Decimal('9.00'))

        # On Sunday: is_day_off is True and required hours is 0.00
        from datetime import date, time
        sun_date = date(2026, 10, 18)  # Sunday
        self.assertTrue(user.is_day_off(sun_date))
        self.assertEqual(user.get_working_hours_for_date(sun_date), Decimal('0.00'))
        # But shift timings are preserved
        s_time, e_time = user.get_shift_timings_for_date(sun_date)
        self.assertEqual(s_time, time(10, 0))
        self.assertEqual(e_time, time(14, 0))

    def test_payroll_zero_deduction_for_custom_off_days(self):
        from decimal import Decimal
        from datetime import date, time, datetime
        import calendar
        from payroll.models import PayrollRun
        from attendance.models import EmployeeAttendanceRecord
        from payroll.utils import compute_payslip_for_user

        org = Organization.objects.create(name='Off Day Payroll Org')
        user = User.objects.create_user(
            username='off_day_employee',
            email='offday@test.org',
            password='Password123!',
            phone='9111111124',
            name='Off Day Employee',
            role='counsellor',
            salary=Decimal('30000.00'),
            employment_type='full_time',
            organization=org,
            weekly_schedule={
                'monday': {'start_time': '10:00:00', 'end_time': '19:00:00', 'is_off': False},
                'tuesday': {'start_time': '10:00:00', 'end_time': '19:00:00', 'is_off': False},
                'wednesday': {'start_time': '10:00:00', 'end_time': '19:00:00', 'is_off': True},
                'thursday': {'start_time': '10:00:00', 'end_time': '19:00:00', 'is_off': False},
                'friday': {'start_time': '10:00:00', 'end_time': '19:00:00', 'is_off': False},
                'saturday': {'start_time': '10:00:00', 'end_time': '19:00:00', 'is_off': False},
                'sunday': {'start_time': '10:00:00', 'end_time': '14:00:00', 'is_off': True},
            }
        )

        from branch.models import Branch
        branch = Branch.objects.create(name='Off Day Branch', organization=org)
        user.branch = branch
        user.save()

        month = 5
        year = 2026
        payroll_run = PayrollRun.objects.create(
            branch=branch,
            month=month,
            year=year,
            generated_by=user,
        )

        # Mark attendance on every non-off day (skip Wednesday and Sunday)
        num_days = calendar.monthrange(year, month)[1]
        for d in range(1, num_days + 1):
            cur_date = date(year, month, d)
            if not user.is_day_off(cur_date):
                from django.utils import timezone as dj_timezone
                tz = dj_timezone.get_current_timezone()
                in_dt = dj_timezone.make_aware(datetime.combine(cur_date, time(10, 0)), tz)
                out_dt = dj_timezone.make_aware(datetime.combine(cur_date, time(19, 0)), tz)
                EmployeeAttendanceRecord.objects.create(
                    user=user,
                    branch=branch,
                    date=cur_date,
                    status='present',
                    checked_in_at=in_dt,
                    checked_out_at=out_dt,
                )

        payslip = compute_payslip_for_user(user, month, year, payroll_run)
        # Wednesday & Sunday were off days, so absence deduction is 0 and full salary is preserved without deduction
        self.assertEqual(payslip.absence_deductions, Decimal('0.00'))
        self.assertEqual(payslip.leave_deductions, Decimal('0.00'))
        self.assertEqual(payslip.basic_salary, Decimal('30000.00'))
        self.assertEqual(payslip.attendance_bonus, Decimal('1000.00'))
        self.assertEqual(payslip.net_salary, Decimal('31000.00'))



