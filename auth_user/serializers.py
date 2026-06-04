from rest_framework import serializers
from .models import User, Organization


class UserSerializer(serializers.ModelSerializer):
    role_display = serializers.CharField(source='get_role_display', read_only=True)
    organization_name = serializers.CharField(source='organization.name', read_only=True)
    profile_pic = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'phone', 'name', 'role', 'role_display', 'is_active', 'branch','organization', 'organization_name', 'profile_pic']

    def get_profile_pic(self, obj):
        if obj.profile_pic:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.profile_pic.url)
            return obj.profile_pic.url
        return None

class UserListSerializer(serializers.ModelSerializer):
    role_display = serializers.CharField(source='get_role_display', read_only=True)
    profile_pic = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'phone', 'name', 'role', 'role_display', 'is_active','created_at', 'profile_pic']

    def get_profile_pic(self, obj):
        if obj.profile_pic:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.profile_pic.url)
            return obj.profile_pic.url
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
        user = User.objects.create_user(password=password, is_active=False, **validated_data)
        return user


class AddUserSerializer(serializers.ModelSerializer):
    organization = serializers.PrimaryKeyRelatedField(
        queryset=Organization.objects.all(), required=False, allow_null=True
    )

    class Meta:
        model = User
        fields = ['username','email','phone','name','role','branch','linked_student','organization']

    def create(self, validated_data):
        request = self.context.get('request')
        if ('organization' not in validated_data or validated_data['organization'] is None) and request is not None:
            request_org = getattr(request.user, 'organization', None)
            if request_org:
                validated_data['organization'] = request_org
        user = User.objects.create_user(password=None, is_active=False, **validated_data)
        return user   

class OrganizationCreateSerializer(serializers.Serializer):
    organization_name = serializers.CharField(max_length=255)
    username = serializers.CharField(max_length=100)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=15)
    name = serializers.CharField(max_length=255)

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    def validate_username(self, value):
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("This username is already taken.")
        return value

    def create(self, validated_data):
        organization = Organization.objects.create(name=validated_data['organization_name'])
        user = User.objects.create_user(
            username=validated_data['username'],
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


class UpdateUserSerializer(serializers.ModelSerializer):
    organization = serializers.PrimaryKeyRelatedField(
        queryset=Organization.objects.all(), required=False, allow_null=True
    )
    profile_pic = serializers.ImageField(required=False, allow_null=True)

    class Meta:
        model = User
        fields = ['username','email','phone','name','role','branch','linked_student','is_active','organization','profile_pic']

    def validate_email(self, value):
        if User.objects.exclude(id=self.instance.id).filter(email=value).exists():
            raise serializers.ValidationError("Email already exists")
        return value

    def validate_username(self, value):
        if User.objects.exclude(id=self.instance.id).filter(username=value).exists():
            raise serializers.ValidationError("Username already exists")
        return value

class UserProfileSerializer(serializers.ModelSerializer):
    organization_name = serializers.CharField(source='organization.name', read_only=True)
    profile_pic = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'phone', 'name', 'role', 'branch', 'linked_student', 'organization', 'organization_name', 'profile_pic']
        read_only_fields = ['id', 'username', 'role', 'branch', 'linked_student', 'organization', 'organization_name'] # These fields cannot be updated via this serializer
    
    def get_profile_pic(self, obj):
        if obj.profile_pic:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.profile_pic.url)
            return obj.profile_pic.url
        return None

    def validate_email(self, value):
        # Ensure email is unique across users, excluding the current user
        if User.objects.filter(email=value).exclude(id=self.instance.id).exists():
            raise serializers.ValidationError("This email is already in use.")
        return value