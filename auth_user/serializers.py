from rest_framework import serializers
from .models import User, Organization
from branch.models import Branch
from django.conf import settings


EMPLOYEE_FIELDS = [
    'employee_id', 'qualification', 'specialization', 'subject_expertise', 'level', 
    'employment_type', 'joining_date', 'hourly_rate', 'session_hours', 'salary', 
    'bank_account', 'ifsc_code', 'pan_number', 'aadhar_number', 'work_start_time', 'work_end_time', 
    'salary_retention_percentage', 'per_paper_rate'
]

class EmployeeFieldsMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request') if hasattr(self, 'context') and self.context else None
        user = getattr(request, 'user', None) if request else None
        if user and hasattr(user, 'organization') and user.organization and not getattr(user, 'is_superuser', False):
            org = user.organization
            qs = Branch.objects.filter(organization=org, is_deleted=False)
        else:
            qs = Branch.objects.filter(is_deleted=False)
        for field_name in ('branch', 'branches'):
            if field_name in self.fields:
                self.fields[field_name].queryset = qs

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        role = getattr(instance, 'role', None)
        emp_type = getattr(instance, 'employment_type', None)
        
        # Inject RBAC fields
        from auth_user.permissions import get_role_config
        role_config = get_role_config(role or '')
        
        accessible_modules = getattr(instance, 'accessible_modules', None)
        if accessible_modules is not None:
            ret['accessible_modules'] = accessible_modules
        else:
            ret['accessible_modules'] = role_config.get('default_modules', [])
            
        ret['canDelete'] = role_config.get('canDelete', False)
        ret['canExport'] = role_config.get('canExport', False)

        try:
            from payroll.utils import EMPLOYEE_ROLES
            all_employee_roles = EMPLOYEE_ROLES + ['faculty']
        except ImportError:
            all_employee_roles = ['branch_manager', 'admin_senior_executive', 'admin_executive', 'front_desk', 'counsellor', 'sales_senior_executive', 'sales_executive', 'tele_caller', 'exam_supervisor', 'paper_checker', 'accountant', 'house_keeping', 'security', 'faculty']
        
        if role not in all_employee_roles:
            for f in EMPLOYEE_FIELDS:
                ret.pop(f, None)
            return ret
            
        if role != 'faculty':
            for f in ['specialization', 'subject_expertise', 'employment_type', 'session_hours']:
                ret.pop(f, None)
                
        if not (role == 'faculty' and emp_type in ['part_time', 'visiting']):
            ret.pop('hourly_rate', None)
            
        exclude_salary = (role == 'faculty' and emp_type in ['part_time', 'visiting']) or role in ['paper_checker', 'exam_supervisor', 'examiner']
        if exclude_salary:
            ret.pop('salary', None)
            
        if role != 'paper_checker':
            ret.pop('per_paper_rate', None)
            
        return ret


    def to_internal_value(self, data):
        # Safely convert data to a mutable dictionary, avoiding deepcopy on file objects
        if hasattr(data, 'getlist'):
            mutable_data = {}
            for k in data.keys():
                lst = data.getlist(k)
                mutable_data[k] = lst if len(lst) > 1 else lst[0]
        else:
            mutable_data = dict(data)

        # Normalize 'branches' to list (user wants explicit list ['id1', 'id2'])
        # Single string is wrapped; comma-separated strings will fail validation (enforces proper array from frontend)
        if 'branches' in mutable_data:
            branches_val = mutable_data.get('branches')
            if isinstance(branches_val, (str, bytes)) and branches_val.strip():
                mutable_data['branches'] = [branches_val.strip()]
            elif isinstance(branches_val, (list, tuple)):
                mutable_data['branches'] = [b.strip() if isinstance(b, (str, bytes)) else b for b in branches_val if b]
            elif branches_val not in (None, '', [], ['']):
                mutable_data['branches'] = [branches_val]

        choice_fields_defaults = {
            'level': 'executive',
            'employment_type': 'full_time'
        }
        for f, default_val in choice_fields_defaults.items():
            if f in mutable_data and mutable_data[f] in ['', 'null', 'undefined', None]:
                # If they send empty string for a choice field, either remove it or set default.
                # Removing it is safer for PATCH, it just keeps the existing value.
                mutable_data.pop(f)

        nullable_fields = ['joining_date', 'work_start_time', 'work_end_time', 'employee_id']
        for f in nullable_fields:
            if f in mutable_data and mutable_data[f] in ['', 'null', 'undefined', None]:
                mutable_data[f] = None
                
        numeric_fields = ['hourly_rate', 'session_hours', 'salary', 'salary_retention_percentage', 'per_paper_rate']
        for f in numeric_fields:
            if f in mutable_data and mutable_data[f] in ['', 'null', 'undefined', None]:
                mutable_data[f] = 0
                
        return super().to_internal_value(mutable_data)

    def validate(self, attrs):

        # We need to call super().validate(attrs) first, but some ModelSerializers
        # might not have a custom validate method, so we handle it safely.
        if hasattr(super(), 'validate'):
            try:
                attrs = super().validate(attrs)
            except TypeError:
                pass
            
        role = attrs.get('role', getattr(self.instance, 'role', None))
        emp_type = attrs.get('employment_type', getattr(self.instance, 'employment_type', None))
        
        try:
            from payroll.utils import EMPLOYEE_ROLES
            all_employee_roles = EMPLOYEE_ROLES + ['faculty']
        except ImportError:
            all_employee_roles = ['branch_manager', 'admin_senior_executive', 'admin_executive', 'front_desk', 'counsellor', 'sales_senior_executive', 'sales_executive', 'tele_caller', 'exam_supervisor', 'paper_checker', 'accountant', 'house_keeping', 'security', 'faculty']

        if role not in all_employee_roles:
            for f in EMPLOYEE_FIELDS:
                attrs.pop(f, None)
        else:
            if role != 'faculty':
                for f in ['specialization', 'subject_expertise', 'employment_type', 'session_hours']:
                    attrs.pop(f, None)
                        
            if not (role == 'faculty' and emp_type in ['part_time', 'visiting']):
                attrs.pop('hourly_rate', None)
                    
            exclude_salary = (role == 'faculty' and emp_type in ['part_time', 'visiting']) or role in ['paper_checker', 'exam_supervisor', 'examiner']
            if exclude_salary:
                attrs.pop('salary', None)
                    
            if role != 'paper_checker':
                attrs.pop('per_paper_rate', None)
                
        return attrs


class UserSerializer(EmployeeFieldsMixin, serializers.ModelSerializer):
    role_display = serializers.CharField(source='get_role_display', read_only=True)
    organization_name = serializers.CharField(source='organization.name', read_only=True)
    profile_pic = serializers.SerializerMethodField()
    branches = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'phone', 'name', 'role', 'role_display', 'is_active', 'branch', 'branches', 'organization', 'organization_name', 'profile_pic', 'accessible_modules'] + EMPLOYEE_FIELDS

    def get_branches(self, obj):
        b_ids = [str(b.id) for b in obj.branches.all()]
        if obj.branch_id and str(obj.branch_id) not in b_ids:
            b_ids.append(str(obj.branch_id))
        return b_ids

    def get_profile_pic(self, obj):
        if obj.profile_pic:
            file_url = obj.profile_pic.url
            # If Azure storage is enabled and URL is relative, build absolute URL
            if settings.USE_AZURE_MEDIA:
                if not file_url.startswith(('http://', 'https://')):
                    # Relative URL with Azure - shouldn't happen but handle it
                    return f"{settings.MEDIA_URL.rstrip('/')}/{file_url.lstrip('/')}"
                return file_url
            else:
                # Local storage - build absolute URI if relative
                if file_url.startswith(('http://', 'https://')):
                    return file_url
                request = self.context.get('request')
                if request is not None:
                    return request.build_absolute_uri(file_url)
                return file_url
        return None

class UserListSerializer(EmployeeFieldsMixin, serializers.ModelSerializer):
    role_display = serializers.CharField(source='get_role_display', read_only=True)
    branch_name = serializers.CharField(source='branch.name', read_only=True)
    profile_pic = serializers.SerializerMethodField()
    branches = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'phone', 'name', 'role', 'role_display', 'is_active', 'created_at', 'branch', 'branch_name', 'branches', 'profile_pic', 'accessible_modules'] + EMPLOYEE_FIELDS

    def get_branches(self, obj):
        b_ids = [str(b.id) for b in obj.branches.all()]
        if obj.branch_id and str(obj.branch_id) not in b_ids:
            b_ids.append(str(obj.branch_id))
        return b_ids

    def get_profile_pic(self, obj):
        if obj.profile_pic:
            file_url = obj.profile_pic.url
            # If Azure storage is enabled and URL is relative, build absolute URL
            if settings.USE_AZURE_MEDIA:
                if not file_url.startswith(('http://', 'https://')):
                    # Relative URL with Azure - shouldn't happen but handle it
                    return f"{settings.MEDIA_URL.rstrip('/')}/{file_url.lstrip('/')}"
                return file_url
            else:
                # Local storage - build absolute URI if relative
                if file_url.startswith(('http://', 'https://')):
                    return file_url
                request = self.context.get('request')
                if request is not None:
                    return request.build_absolute_uri(file_url)
                return file_url
        return None

class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ['id', 'name', 'logo_url', 'footer_text', 'primary_color', 'website_url', 'created_at']
        read_only_fields = ['id', 'created_at']


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    organization = serializers.PrimaryKeyRelatedField(
        queryset=Organization.objects.all(), required=False, allow_null=True
    )

    class Meta:
        model = User
        fields = ['username', 'email', 'phone', 'name', 'role', 'password', 'organization']

    def create(self, validated_data):
        password = validated_data.pop('password')
        request = self.context.get('request')
        if ('organization' not in validated_data or validated_data['organization'] is None) and request is not None:
            request_org = getattr(request.user, 'organization', None)
            if getattr(request.user, 'is_authenticated', False) and request_org:
                validated_data['organization'] = request_org
        
        # Auto-generate username for self-registered users (usually students/parents from portal)
        role = validated_data.get('role', 'student')
        if 'username' not in validated_data or not validated_data['username']:
            from auth_user.utils import generate_username
            username, _ = generate_username(role=role, branch=None)
            validated_data['username'] = username
            
        user = User.objects.create_user(password=password, is_active=False, **validated_data)
        return user


class AddUserSerializer(EmployeeFieldsMixin, serializers.ModelSerializer):
    organization = serializers.PrimaryKeyRelatedField(
        queryset=Organization.objects.all(), required=False, allow_null=True
    )
    branch = serializers.PrimaryKeyRelatedField(
        queryset=Branch.objects.filter(is_deleted=False),
        required=False,
        allow_null=True
    )
    branches = serializers.PrimaryKeyRelatedField(
        queryset=Branch.objects.filter(is_deleted=False),
        many=True,
        required=False,
        allow_null=True
    )
    work_start_time = serializers.TimeField(required=False, allow_null=True)
    work_end_time = serializers.TimeField(required=False, allow_null=True)

    class Meta:
        model = User
        fields = ['username','email','phone','name','role','branch','branches','linked_students','organization', 'accessible_modules'] + EMPLOYEE_FIELDS
        extra_kwargs = {
            'username': {'required': False, 'allow_null': True, 'allow_blank': True}
        }

    def to_internal_value(self, data):
        # Delegate to EmployeeFieldsMixin.to_internal_value (normalizes branches to list)
        return super().to_internal_value(data)

    def validate_role(self, value):
        if value in ['student', 'parents', 'super_admin']:
            raise serializers.ValidationError(f"Users with role '{value}' cannot be created directly from the Add User interface. This role is managed automatically.")
        return value

    def create(self, validated_data):
        linked_students = validated_data.pop('linked_students', None)
        extra_branches = validated_data.pop('branches', None)
        request = self.context.get('request')
        if ('organization' not in validated_data or validated_data['organization'] is None) and request is not None:
            request_org = getattr(request.user, 'organization', None)
            if request_org:
                validated_data['organization'] = request_org

        role = validated_data.get('role')
        branch = validated_data.get('branch')
        
        # ── Sync branch ↔ branches ────────────────────────────────────────
        # Build the final set of branches from both sources
        if extra_branches is None:
            branch_set = []
        else:
            branch_set = list(extra_branches) if isinstance(extra_branches, (list, tuple, set)) else [extra_branches]

        if branch and branch not in branch_set:
            branch_set.insert(0, branch)   # primary branch first

        # Auto-generate username for employees
        from auth_user.utils import generate_username
        username, _ = generate_username(role=role, branches=branch_set)
        validated_data['username'] = username

        user = User.objects.create_user(password=None, is_active=True, **validated_data)

        if branch_set:
            user.branches.set(branch_set)
            # If no primary branch was given, promote first of branches
            if not user.branch:
                user.branch = branch_set[0]
                user.save(update_fields=['branch'])
        # ─────────────────────────────────────────────────────────────────

        if linked_students:
            user.linked_students.set(linked_students)
            # Also create ParentLink records so dashboard and other parent features work
            from students.models import ParentLink, Student
            for student_user in linked_students:
                try:
                    student = Student.objects.get(user=student_user)
                    ParentLink.objects.get_or_create(
                        student=student,
                        parent=user,
                        defaults={
                            'relationship': 'father',
                            'is_primary': True,
                        }
                    )
                except Student.DoesNotExist:
                    # Student profile may not exist yet
                    pass
        return user

class OrganizationCreateSerializer(serializers.Serializer):
    organization_name = serializers.CharField(max_length=255)
    username = serializers.CharField(max_length=100, required=False, allow_blank=True)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=15)
    name = serializers.CharField(max_length=255)

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    def validate_username(self, value):
        if value and User.objects.filter(username=value).exists():
            raise serializers.ValidationError("This username is already taken.")
        return value

    def create(self, validated_data):
        organization = Organization.objects.create(name=validated_data['organization_name'])
        
        from auth_user.utils import generate_username
        username, _ = generate_username(role='super_admin')
        
        user = User.objects.create_user(
            username=username,
            email=validated_data['email'],
            password=None,
            role='super_admin',
            organization=organization,
            phone=validated_data['phone'],
            name=validated_data['name'],
            is_active=False,
        )
        return {
            'organization': organization,
            'user': user,
        }

class PasswordSetSerializer(serializers.Serializer):
    token = serializers.CharField()
    password = serializers.CharField(write_only=True, min_length=6)
    confirm_password = serializers.CharField(write_only=True, min_length=6)

    def validate(self, attrs):
        if attrs['password'] != attrs['confirm_password']:
            raise serializers.ValidationError("Passwords do not match")
        return attrs


class VerifyOTPSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField(max_length=6)
    
class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField()
    organization = serializers.UUIDField(required=False, allow_null=True)


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()

class ResetPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField(max_length=6)
    password = serializers.CharField(min_length=6,write_only=True)
    confirm_password = serializers.CharField(min_length=6,write_only=True)

    def validate(self, attrs):
        if attrs['password'] != attrs['confirm_password']:
            raise serializers.ValidationError("Passwords do not match")
        return attrs


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(min_length=6, write_only=True)
    confirm_new_password = serializers.CharField(min_length=6, write_only=True)

    def validate(self, attrs):
        if attrs['new_password'] != attrs['confirm_new_password']:
            raise serializers.ValidationError({"confirm_new_password": "Passwords do not match"})

        # Removed as per request
        # if attrs['current_password'] == attrs['new_password']:
        #     raise serializers.ValidationError({"new_password": "New password must be different from current password"})

        return attrs


class UpdateUserSerializer(EmployeeFieldsMixin, serializers.ModelSerializer):
    organization = serializers.PrimaryKeyRelatedField(
        queryset=Organization.objects.all(), required=False, allow_null=True
    )
    branch = serializers.PrimaryKeyRelatedField(
        queryset=Branch.objects.filter(is_deleted=False),
        required=False,
        allow_null=True
    )
    branches = serializers.PrimaryKeyRelatedField(
        queryset=Branch.objects.filter(is_deleted=False),
        many=True,
        required=False,
        allow_null=True
    )
    profile_pic = serializers.ImageField(required=False, allow_null=True)
    work_start_time = serializers.TimeField(required=False, allow_null=True)
    work_end_time = serializers.TimeField(required=False, allow_null=True)

    class Meta:
        model = User
        fields = ['username','email','phone','name','role','branch','branches','linked_students','is_active','organization','profile_pic', 'accessible_modules'] + EMPLOYEE_FIELDS

    def validate_email(self, value):
        if User.objects.exclude(id=self.instance.id).filter(email=value).exists():
            raise serializers.ValidationError("Email already exists")
        return value

    def validate_username(self, value):
        if User.objects.exclude(id=self.instance.id).filter(username=value).exists():
            raise serializers.ValidationError("Username already exists")
        return value

    def update(self, instance, validated_data):
        extra_branches = validated_data.pop('branches', None)
        linked_students = validated_data.pop('linked_students', None)
        instance = super().update(instance, validated_data)

        # ── Sync branch ↔ branches ────────────────────────────────────────
        # Respect exact list sent in PATCH/PUT (fixes bug where sending 1 branch
        # when user had 2 did not remove the extra branch from M2M)
        if extra_branches is not None:
            branch_set = list(extra_branches) if extra_branches else []
            instance.branches.set(branch_set)

            # If primary branch FK is no longer in the new branches list,
            # promote the first one from the list (or clear it)
            if branch_set:
                if not instance.branch or instance.branch not in branch_set:
                    instance.branch = branch_set[0]
                    instance.save(update_fields=['branch'])
            elif instance.branch:
                # No branches left — clear primary FK too
                instance.branch = None
                instance.save(update_fields=['branch'])
        elif 'branch' in validated_data and validated_data.get('branch'):
            # Only primary branch was updated — ensure it's in the M2M relation
            if not instance.branches.filter(id=validated_data['branch'].id).exists():
                instance.branches.add(validated_data['branch'])
        # ─────────────────────────────────────────────────────────────────
        if linked_students is not None:
            # linked_students may be list of User instances or pks (UUIDs)
            instance.linked_students.set(linked_students)
            # Sync ParentLink records for consistency with new source-of-truth model
            from students.models import ParentLink, Student
            # Clear links not in the new set
            if linked_students:
                # Convert to list of pks for safe lookup
                student_pks = [ls.pk if hasattr(ls, 'pk') else ls for ls in linked_students]
                ParentLink.objects.filter(parent=instance).exclude(
                    student__user__in=student_pks
                ).delete()
                for student_pk in student_pks:
                    try:
                        student = Student.objects.get(user_id=student_pk)
                        ParentLink.objects.get_or_create(
                            student=student,
                            parent=instance,
                            defaults={
                                'relationship': 'father',
                                'is_primary': len(student_pks) == 1,
                            }
                        )
                    except Student.DoesNotExist:
                        pass
            else:
                ParentLink.objects.filter(parent=instance).delete()

        # Sync all employee fields to FacultyProfile if it exists
        if instance.role == 'faculty':
            try:
                from faculty.models import FacultyProfile
                fp = FacultyProfile.objects.get(user=instance)
                fp.qualification = instance.qualification
                fp.specialization = instance.specialization
                fp.subject_expertise = instance.subject_expertise
                fp.level = instance.level
                fp.employment_type = instance.employment_type
                fp.joining_date = instance.joining_date
                fp.hourly_rate = instance.hourly_rate
                fp.session_hours = instance.session_hours
                fp.salary = instance.salary
                fp.salary_retention_percentage = instance.salary_retention_percentage
                fp.bank_account = instance.bank_account
                fp.ifsc_code = instance.ifsc_code
                fp.pan_number = instance.pan_number
                fp.work_start_time = instance.work_start_time
                fp.work_end_time = instance.work_end_time
                fp.save(update_fields=[
                    'qualification', 'specialization', 'subject_expertise', 'level',
                    'employment_type', 'joining_date', 'hourly_rate', 'session_hours',
                    'salary', 'salary_retention_percentage', 'bank_account',
                    'ifsc_code', 'pan_number', 'work_start_time', 'work_end_time',
                ])
            except:
                pass
                
        return instance

class UserProfileSerializer(EmployeeFieldsMixin, serializers.ModelSerializer):
    organization_name = serializers.CharField(source='organization.name', read_only=True)
    branch_name = serializers.CharField(source='branch.name', read_only=True)
    branch_details = serializers.SerializerMethodField()
    branches_details = serializers.SerializerMethodField()
    profile_pic = serializers.ImageField(required=False, allow_null=True)
    role_display = serializers.CharField(source="get_role_display", read_only=True)
    linked_student_names = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'phone', 'name', 'role', 'branch', 'branch_name', 'branch_details', 'branches', 'branches_details', 'linked_students', 'organization', 'organization_name', 'profile_pic', 'role_display', 'linked_student_names'] + EMPLOYEE_FIELDS
        read_only_fields = ['id', 'username', 'role', 'branch', 'branch_name', 'branch_details', 'branches', 'branches_details', 'linked_students', 'organization', 'organization_name', 'linked_student_names']

    def get_branch_details(self, obj):
        if obj.branch:
            return {'id': str(obj.branch.id), 'name': obj.branch.name}
        return None

    def get_branches_details(self, obj):
        return [{'id': str(branch.id), 'name': branch.name} for branch in obj.branches.all()]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        
        if instance.role in ['parent', 'parents']:
            from students.models import Student, ParentLink
            student_profiles = set()
            student_names = set()
            
            if instance.linked_students.exists():
                for sp in Student.objects.filter(user__in=instance.linked_students.all()):
                    student_profiles.add(str(sp.id))
                    student_names.add(sp.full_name)
                    
            for sp in Student.objects.filter(parent_links__parent=instance):
                student_profiles.add(str(sp.id))
                student_names.add(sp.full_name)
                
            data['linked_students'] = list(student_profiles)
            data['linked_student_names'] = list(student_names)
        else:
            data['linked_student_names'] = list(instance.linked_students.values_list("name", flat=True))

        if instance.profile_pic:
            file_url = instance.profile_pic.url
            # If Azure storage is enabled and URL is relative, build absolute URL
            if settings.USE_AZURE_MEDIA:
                if not file_url.startswith(('http://', 'https://')):
                    data['profile_pic'] = f"{settings.MEDIA_URL.rstrip('/')}/{file_url.lstrip('/')}"
                else:
                    data['profile_pic'] = file_url
            else:
                # Local storage - build absolute URI if relative
                if file_url.startswith(('http://', 'https://')):
                    data['profile_pic'] = file_url
                else:
                    request = self.context.get('request')
                    if request is not None:
                        data['profile_pic'] = request.build_absolute_uri(file_url)
                    else:
                        data['profile_pic'] = file_url
        else:
            data['profile_pic'] = None
        return data

    def validate_email(self, value):
        if User.objects.exclude(id=self.instance.id).filter(email=value).exists():
            raise serializers.ValidationError("This email is already in use.")
        return value

    def get_linked_student_names(self, obj):
        # The actual data is populated in to_representation to avoid duplicate queries
        return []

from .models import NotificationHistory

class NotificationHistorySerializer(serializers.ModelSerializer):
    notification_type = serializers.SerializerMethodField()
    route = serializers.SerializerMethodField()

    class Meta:
        model = NotificationHistory
        fields = ['id', 'title', 'body', 'data', 'notification_type', 'route', 'is_read', 'created_at']

    def get_notification_type(self, obj):
        if isinstance(obj.data, dict):
            return obj.data.get('type', 'general')
        return 'general'

    def get_route(self, obj):
        if isinstance(obj.data, dict):
            # Fallback to the 'type' field or empty string if 'route' is missing/null
            return obj.data.get('route') or obj.data.get('type') or ""
        return ""