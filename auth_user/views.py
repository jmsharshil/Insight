from auth_user.serializers import ChangePasswordSerializer
from rest_framework_simplejwt.authentication import JWTAuthentication
from django.shortcuts import render
from core.pagination import paginate_queryset
from django.db.models import Q

# Create your views here.
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.filters import SearchFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend
from core.utils import apply_filters
from .models import User, Organization, EmailOTP, PasswordSetToken
from .serializers import (
    AddUserSerializer,
    RegisterSerializer,
    LoginSerializer,
    VerifyOTPSerializer,
    ForgotPasswordSerializer,
    ResetPasswordSerializer,
    PasswordSetSerializer,
    OrganizationCreateSerializer,
    OrganizationSerializer,
    UserSerializer,
    UserListSerializer,
    UpdateUserSerializer,
    UserProfileSerializer,
    ChangePasswordSerializer
)
from .utils import send_otp_email, send_password_set_email
from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import RefreshToken
from leads.models import Lead
from leads.serializers import LeadDetailSerializer
from rest_framework_simplejwt.authentication import JWTAuthentication

ROLES_REQUIRING_LOGIN_OTP_BYPASS = {'student', 'parents'}
RESEND_OTP_COOLDOWN_SECONDS = 30


def build_login_success_response(user, request):
    """Builds the same response payload the old LoginAPIView returned directly."""
    refresh = RefreshToken.for_user(user)

    profile_pic_url = None
    if user.profile_pic and hasattr(user.profile_pic, 'url'):
        profile_pic_url = request.build_absolute_uri(user.profile_pic.url)

    from students.models import Student, ParentLink
    actual_student_ids = []
    if user.role == 'student':
        student_profile = Student.objects.filter(user=user).first()
        if student_profile:
            actual_student_ids = [str(student_profile.id)]
    elif user.role == 'parents':
        parent_links = ParentLink.objects.filter(parent=user).select_related('student')
        actual_student_ids = [str(pl.student.id) for pl in parent_links if pl.student]

    from auth_user.permissions import get_role_config
    role_config = get_role_config(user.role)
    accessible_modules = getattr(user, 'accessible_modules', None)
    if accessible_modules is None:
        accessible_modules = role_config.get('default_modules', [])

    return {
        "message": "Login successful",
        "access": str(refresh.access_token),
        "refresh": str(refresh),
        "user": {
            "id": str(user.id),
            "username": user.username,
            "email": user.email,
            "phone": user.phone,
            "name": user.name,
            "role": user.role,
            "role_display": user.get_role_display(),
            "profile_pic": profile_pic_url,
            "organization": str(user.organization.id) if user.organization else None,
            "organization_name": user.organization.name if user.organization else None,
            "linked_students": actual_student_ids,
            "accessible_modules": accessible_modules,
            "canDelete": role_config.get('canDelete', False),
            "canExport": role_config.get('canExport', False),
        }
    }

class RegisterAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            user = serializer.save()
            otp = EmailOTP.generate_otp()
            EmailOTP.objects.create(
                user=user,
                otp=otp
            )
            send_otp_email(user, otp)
            return Response({
                "message": "OTP sent to email"
            })
        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )
    

class VerifyOTPAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):

        serializer = VerifyOTPSerializer(data=request.data)

        if serializer.is_valid():
            email = serializer.validated_data['email']
            otp = serializer.validated_data['otp']

            otp_obj = EmailOTP.objects.filter(user__email=email, otp=otp, is_verified=False).last()
            user = User.objects.filter(email=email).first()
            if not user:
                return Response({"error": "User not found"}, status=404)
            
            otp_obj = EmailOTP.objects.filter(user=user,otp=otp,is_verified=False).last()

            if not otp_obj:
                return Response({"error": "Invalid OTP"}, status=400)

            if otp_obj.is_expired():
                return Response({"error": "OTP expired"}, status=400)

            otp_obj.is_verified = True
            otp_obj.save()

            user = otp_obj.user
            user.is_active = True
            user.save()
            return Response({"message": "Account verified successfully"})

        return Response(serializer.errors, status=400)
        
class LoginAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data['email']
            password = serializer.validated_data['password']
            organization_id = serializer.validated_data.get('organization')
            users = User.objects.filter(email=email)
            if organization_id:
                users = users.filter(organization_id=organization_id)
            user = None
            for candidate in users:
                candidate_user = authenticate(request, username=candidate.username, password=password)
                if candidate_user is not None:
                    user = candidate_user
                    break

            if user is None:
                return Response({
                    "error": "Incorrect email or password"
                }, status=400)
            if not user.is_active:
                return Response({"error": "Account is not verified"}, status=400)

            #for testing:
            return Response(build_login_success_response(user, request)) #for live remove it

            # ── Existing behavior preserved exactly for student/parent ──
            if user.role in ROLES_REQUIRING_LOGIN_OTP_BYPASS:
                return Response(build_login_success_response(user, request))

            # ── Everyone else: require a second OTP step ──
            otp = EmailOTP.generate_otp()
            EmailOTP.objects.create(user=user, otp=otp)
            from .utils import send_login_otp
            send_login_otp(user, otp)

            return Response({
                "otp_required": True,
                "message": "OTP sent to your registered email/WhatsApp. Please verify to complete login.",
                "email": user.email,
                "organization": str(user.organization.id) if user.organization else None,
                "organization_name": user.organization.name if user.organization else None,
            })

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class LoginVerifyOTPAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = VerifyOTPSerializer(data=request.data)  # just email + otp, already exists
        if serializer.is_valid():
            email = serializer.validated_data['email']
            otp = serializer.validated_data['otp']
            organization_id = request.data.get('organization')

            candidates = User.objects.filter(email=email)
            if organization_id:
                candidates = candidates.filter(organization_id=organization_id)

            otp_obj = EmailOTP.objects.filter(
                user__in=candidates, otp=otp, is_verified=False
            ).order_by('-created_at').first()

            if not otp_obj:
                return Response({"error": "Invalid OTP"}, status=400)
            if otp_obj.is_expired():
                return Response({"error": "OTP expired"}, status=400)

            otp_obj.is_verified = True
            otp_obj.save()

            user = otp_obj.user
            if not user.is_active:
                return Response({"error": "Account is not verified"}, status=400)

            return Response(build_login_success_response(user, request))

        return Response(serializer.errors, status=400)
  
class ResendLoginOTPAPIView(APIView):
    """
    POST /api/auth/login/resend-otp/
 
    Issues a fresh login-verification OTP for a user already mid-login
    (i.e. password already checked, waiting on 2nd factor).
 
    Body: { "email": "...", "organization": "optional-uuid" }
 
    Notes:
      - Does NOT re-check the password. This assumes the frontend only
        shows a "resend code" button on the OTP-entry screen, which is
        only reachable after LoginAPIView already returned otp_required.
      - Old unverified LoginOTP rows are left in place but become dead:
        LoginVerifyOTPAPIView only ever checks the most recent one
        (order_by('-created_at').first()), so a stale code silently
        stops working the moment a new one is issued.
      - A short cooldown prevents spamming the email/WhatsApp send.
    """
    permission_classes = [AllowAny]
 
    def post(self, request):
        email = request.data.get('email')
 
        if not email:
            return Response({"error": "Email is required"}, status=status.HTTP_400_BAD_REQUEST)
 
        candidates = User.objects.filter(email=email)
        
        user = candidates.first()
        if not user:
            return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)
 
        if not user.is_active:
            return Response({"error": "Account is not verified"}, status=status.HTTP_400_BAD_REQUEST)
 
        if user.role in ROLES_REQUIRING_LOGIN_OTP_BYPASS:
            return Response(
                {"error": "This account does not require OTP verification."},
                status=status.HTTP_400_BAD_REQUEST,
            )
 
        # ── Cooldown: block rapid repeat requests ──
        last_otp = EmailOTP.objects.filter(user=user).order_by('-created_at').first()
        if last_otp:
            seconds_since = (timezone.now() - last_otp.created_at).total_seconds()
            if seconds_since < RESEND_OTP_COOLDOWN_SECONDS:
                wait = int(RESEND_OTP_COOLDOWN_SECONDS - seconds_since)
                return Response(
                    {"error": f"Please wait {wait} seconds before requesting another code."},
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                )
 
        otp = EmailOTP.generate_otp()
        EmailOTP.objects.create(user=user, otp=otp)
        from .utils import send_login_otp_resend
        send_login_otp_resend(user, otp)
 
        return Response({
            "message": "A new verification code has been sent to your registered email/WhatsApp.",
            "email": user.email,
        })

class OrganizationCreateAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = OrganizationCreateSerializer(data=request.data)
        if serializer.is_valid():
            result = serializer.save()
            user = result['user']
            organization = result['organization']
            token = PasswordSetToken.generate_token()
            PasswordSetToken.objects.create(user=user, token=token)
            send_password_set_email(user, token)
            return Response({
                "message": "Organization and super admin user created successfully. Password setup email sent.",
                "organization_id": str(organization.id),
                "user_id": str(user.id),
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class AddUserAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.role != 'super_admin':
            return Response({"error": "You do not have permission to add users."}, status=status.HTTP_403_FORBIDDEN)

        serializer = AddUserSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            # Validate branch for faculty
            if serializer.validated_data.get('role') == 'faculty' and not serializer.validated_data.get('branch'):
                return Response({"branch": ["Branch is required when creating a faculty user."]}, status=status.HTTP_400_BAD_REQUEST)

            user = serializer.save()
            
            # Automatically create FacultyProfile for faculty users
            if user.role == 'faculty':
                try:
                    from faculty.models import FacultyProfile
                    from faculty.utils import generate_employee_id
                    from django.utils import timezone
                    if not FacultyProfile.objects.filter(user=user).exists():
                        emp_id = generate_employee_id(user.branch)
                        from faculty.utils import generate_faculty_qr_code
                        qr_file = generate_faculty_qr_code(emp_id)
                        fp = FacultyProfile.objects.create(
                            user=user,
                            branch=user.branch,
                            employee_id=emp_id,
                            qualification="N/A",
                            specialization="N/A",
                            joining_date=timezone.now().date(),
                            employment_type=user.employment_type,
                            hourly_rate=user.hourly_rate,
                            session_hours=user.session_hours,
                            salary=user.salary,
                            salary_retention_percentage=user.salary_retention_percentage
                        )
                        if qr_file:
                            fp.qr_code.save(qr_file.name, qr_file, save=True)
                except Exception as e:
                    # If faculty profile fails to create, log it but don't break the user creation
                    pass

            token = PasswordSetToken.generate_token()
            PasswordSetToken.objects.create(user=user, token=token)
            send_password_set_email(user, token)
            return Response({
                "message": "User created successfully. Password setup email sent.",
                "user_id": str(user.id),
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class PasswordSetAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        data = request.data.copy() if hasattr(request.data, 'copy') else dict(request.data)
        if 'token' not in data and 'token' in request.query_params:
            data['token'] = request.query_params['token']

        serializer = PasswordSetSerializer(data=data)
        if serializer.is_valid():
            token = serializer.validated_data['token']
            password = serializer.validated_data['password']

            token_obj = PasswordSetToken.objects.filter(token=token, is_used=False).last()
            if not token_obj:
                return Response({"error": "Invalid or expired token."}, status=status.HTTP_400_BAD_REQUEST)

            if token_obj.is_expired():
                return Response({"error": "Password set link expired."}, status=status.HTTP_400_BAD_REQUEST)

            token_obj.is_used = True
            token_obj.save()

            user = token_obj.user
            user.set_password(password)
            user.is_active = True
            user.save()
            return Response({"message": "Password set successfully. You may now log in."})

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    

class ForgotPasswordAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)

        if serializer.is_valid():
            email = serializer.validated_data['email']
            user = User.objects.filter(email=email).first()
            if not user:
                return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)
            
            otp = EmailOTP.generate_otp()
            EmailOTP.objects.create(user=user,otp=otp)
            send_otp_email(user, otp)
            return Response({"message": "OTP sent successfully"})

        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )
    
class ResetPasswordAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)

        if serializer.is_valid():
            email = serializer.validated_data['email']
            otp = serializer.validated_data['otp']
            password = serializer.validated_data['password']

            otp_obj = EmailOTP.objects.filter(user__email=email, otp=otp, is_verified=False).last()
            if not otp_obj:
                return Response({"error": "Invalid OTP"}, status=status.HTTP_400_BAD_REQUEST)

            if otp_obj.is_expired():
                return Response({"error": "OTP expired"}, status=status.HTTP_400_BAD_REQUEST)

            otp_obj.is_verified = True
            otp_obj.save()

            user = otp_obj.user
            user.set_password(password)
            user.save()

            return Response({"message": "Password reset successful"})

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ChangePasswordAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        user = request.user
        current_password = serializer.validated_data['current_password']
        new_password = serializer.validated_data['new_password']

        if not user.check_password(current_password):
            return Response(
                {"current_password": "Current password is incorrect"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(new_password)
        user.save(update_fields=['password'])

        return Response({"message": "Password changed successfully"}, status=status.HTTP_200_OK)

class ParentStudentProfileAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        parent_user = request.user

        if parent_user.role != 'parents':
            return Response(
                {"success": False, "message": "Only parent users can access this endpoint."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Prefer ParentLink as source of truth (per updated architecture)
        from students.models import ParentLink, Student
        from leads.models import Lead
        from leads.serializers import LeadDetailSerializer
        parent_link = ParentLink.objects.select_related('student', 'student__user').filter(
            parent=parent_user, is_primary=True
        ).first()
        if not parent_link:
            parent_link = ParentLink.objects.select_related('student', 'student__user').filter(
                parent=parent_user
            ).first()
        
        if not parent_link:
            # Fallback to M2M
            student_user = parent_user.linked_students.first()
            if not student_user:
                return Response(
                    {"success": False, "message": "No student is linked to this parent account."},
                    status=status.HTTP_404_NOT_FOUND,
                )
            try:
                student = Student.objects.get(user=student_user)
            except Student.DoesNotExist:
                student = None
        else:
            student = parent_link.student
            student_user = student.user if student else None

        if not student:
            return Response(
                {"success": False, "message": "Linked student profile not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        from leads.models import Lead
        lead = Lead.objects.filter(email__iexact=student.email).order_by('-created_at').first()
        if not lead:
            lead = Lead.objects.filter(phone_student=student.phone_student).order_by('-created_at').first()

        student_data = {
            "id": str(student.id),
            "admission_number": student.admission_number,
            "username": getattr(student_user, 'username', ''),
            "email": student.email,
            "phone": student.phone_student,
            "name": student.full_name,
            "role": "student",
            "batch": student.current_batch_name,
            "photo": request.build_absolute_uri(student.photo.url) if student.photo else None,
        }

        return Response(
            {
                "success": True,
                "data": {
                    "parent": {
                        "id": str(parent_user.id),
                        "email": parent_user.email,
                        "name": parent_user.name,
                        "relationship": parent_link.relationship if parent_link else "parent",
                    },
                    "student": student_data,
                    "student_lead_profile": LeadDetailSerializer(lead).data if lead else None,
                },
            },
            status=status.HTTP_200_OK,
        )
    

from django.shortcuts import get_object_or_404

class UpdateUserAPIView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get_user(self, request, user_id):
        return get_object_or_404(User, id=user_id, organization=request.user.organization)

    def get(self, request, user_id):
        user = self.get_user(request, user_id)
        serializer = UserSerializer(user, context={'request': request})
        return Response(serializer.data)

    def put(self, request, user_id):
        user = self.get_user(request, user_id)

        serializer = UpdateUserSerializer(
            user,
            data=request.data,
            context={'request': request}
        )

        if serializer.is_valid():
            serializer.save()
            return Response({
                "success": True,
                "message": "User updated successfully",
                "data": serializer.data
            })

        return Response(serializer.errors, status=400)

    def patch(self, request, user_id):
        user = self.get_user(request, user_id)

        serializer = UpdateUserSerializer(
            user,
            data=request.data,
            partial=True,
            context={'request': request}
        )

        if serializer.is_valid():
            serializer.save()
            return Response({
                "success": True,
                "message": "User updated successfully",
                "data": serializer.data
            })

        return Response(serializer.errors, status=400)
    
class DeleteUserAPIView(APIView):
    permission_classes = [AllowAny]

    def delete(self, request, user_id):
        user = get_object_or_404(User, id=user_id, organization=request.user.organization)

        # user.is_active = False
        # user.save(update_fields=['is_active'])

        user.delete()

        return Response({
            "success": True,
            "message": "User deleted successfully"
        })

class UserListAPIView(APIView):
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['is_active', 'role', 'branch', 'organization']
    search_fields = ['name', 'email', 'phone']
    ordering_fields = '__all__'
    pagination_class = None

    def get(self, request):
        from django.db.models import Q
        if request.user.is_superuser:
            users = User.objects.select_related('branch').all().order_by('-created_at')
        elif request.user.role == 'super_admin':
            users = User.objects.select_related('branch').filter(
                Q(organization=request.user.organization) | Q(is_superuser=True)
            ).order_by('-created_at')
        else:
            users = User.objects.select_related('branch').filter(organization=request.user.organization).order_by('-created_at')
        roles = self.request.query_params.getlist('role')
        is_active = self.request.query_params.get('is_active')
        branch = self.request.query_params.get('branch')  # explicit support for branch param

        if roles:
            # Handle comma-separated list if passed as ?role=admin,student
            if len(roles) == 1 and ',' in roles[0]:
                roles = [r.strip() for r in roles[0].split(',')]
            users = users.filter(role__in=roles)
            
        if is_active is not None:  # support ?is_active=true/false or 1/0
            users = users.filter(is_active=is_active.lower() in ('true', '1', 'yes') if isinstance(is_active, str) else bool(is_active))
        
        if branch:
            users = users.filter(branch_id=branch)  # support both ?branch=uuid and via filter backend

        users = apply_filters(self, request, users)
        serializer = UserListSerializer(users, many=True)
        return Response({
            'success': True,
            'data': serializer.data
        }, status=status.HTTP_200_OK)

class UserProfileAPIView(APIView):
    parser_classes = [MultiPartParser, FormParser]
    def get(self, request):
        """
        Get details of the currently authenticated user.
        """
        serializer = UserProfileSerializer(request.user, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    def put(self, request):
        """
        Update name and email for the currently authenticated user.
        """
        user = request.user
        serializer = UserProfileSerializer(user, data=request.data, partial=True, context={'request': request}) # Use partial=True to allow partial updates
        if serializer.is_valid():
            serializer.save()
            return Response({
                "success": True,
                "message": "Profile updated successfully",
                "data": serializer.data
            }, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class OrganizationDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not request.user.organization:
            return Response({"error": "User does not belong to an organization."}, status=status.HTTP_404_NOT_FOUND)
        
        serializer = OrganizationSerializer(request.user.organization)
        return Response({
            "success": True,
            "data": serializer.data
        })

    def patch(self, request):
        if not request.user.organization:
            return Response({"error": "User does not belong to an organization."}, status=status.HTTP_404_NOT_FOUND)
        
        # Optionally, restrict this to super_admin or admin roles
        if request.user.role != 'super_admin':
            return Response({"error": "You do not have permission to update organization details."}, status=status.HTTP_403_FORBIDDEN)

        serializer = OrganizationSerializer(request.user.organization, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({
                "success": True,
                "message": "Organization updated successfully",
                "data": serializer.data
            })
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class RegisterFCMTokenView(APIView):
    """
    POST /api/auth/fcm-token/

    Register or update the device FCM push notification token for the
    currently authenticated user.

    Request body:
        { "fcm_token": "<device_token_from_firebase>" }

    The mobile app should call this endpoint:
      - After the user logs in
      - When Firebase issues a new token (onTokenRefresh)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        GET /api/auth/fcm-token/
        Return the currently registered FCM token for the user.
        """
        fcm_token = getattr(request.user, 'fcm_token', '')
        return Response({
            "success": True,
            "data": {
                "fcm_token": fcm_token,
                "is_registered": bool(fcm_token)
            }
        }, status=status.HTTP_200_OK)

    def post(self, request):
        fcm_token = request.data.get("fcm_token", "").strip()
        if not fcm_token:
            return Response(
                {"detail": "'fcm_token' is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Bug fix: clear this token from other users to prevent cross-user notifications on shared devices.
        from django.contrib.auth import get_user_model
        User = get_user_model()
        User.objects.filter(fcm_token=fcm_token).exclude(id=request.user.id).update(fcm_token="")

        request.user.fcm_token = fcm_token
        request.user.save(update_fields=["fcm_token"])

        return Response({"detail": "FCM token registered successfully."}, status=status.HTTP_200_OK)

    def delete(self, request):
        """
        DELETE /api/auth/fcm-token/
        Clear the FCM token (e.g. on logout so no notifications are sent).
        """
        request.user.fcm_token = ""
        request.user.save(update_fields=["fcm_token"])
        return Response({"detail": "FCM token cleared."}, status=status.HTTP_200_OK)

class ToggleUserStatusAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, user_id):
        user = get_object_or_404(User, id=user_id, organization=request.user.organization)
        is_active = request.data.get('is_active')
        
        if is_active is None:
            return Response(
                {"success": False, "message": "is_active field is required."},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        if not isinstance(is_active, bool):
            return Response(
                {"success": False, "message": "is_active must be a boolean value."},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        user.is_active = is_active
        user.save(update_fields=['is_active'])
        
        action_str = "activated" if is_active else "deactivated"
        return Response({
            "success": True,
            "message": f"User {action_str} successfully",
            "data": {
                "user_id": str(user.id),
                "is_active": user.is_active
            }
        }, status=status.HTTP_200_OK)


class TestNotificationAPIView(APIView):
    """
    POST /api/auth/test-notification/
    
    Trigger a manual push notification for testing.
    Payload:
    {
      "title": "Test Title",
      "body": "Test Message",
      "user_id": "optional-uuid" // defaults to self
    }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        title = request.data.get("title", "Test Notification")
        body = request.data.get("body", "This is a test message from the API!")
        user_id = request.data.get("user_id")
        manual_token = request.data.get("fcm_token")
        
        target_email = "manual token"
        target_user_id = None

        if manual_token:
            actual_token = manual_token
            if user_id:
                try:
                    target_user = User.objects.get(id=user_id)
                    target_email = target_user.email
                    target_user_id = target_user.id
                except User.DoesNotExist:
                    pass
        else:
            if user_id:
                target_user = get_object_or_404(User, id=user_id)
            else:
                target_user = request.user
                
            # Ensure we have the absolute latest data from DB
            target_user.refresh_from_db()
            target_email = target_user.email
            target_user_id = target_user.id

            actual_token = getattr(target_user, 'fcm_token', '')
            if not actual_token or not actual_token.strip():
                return Response(
                    {"success": False, "message": f"User {target_email} does not have an FCM token registered."},
                    status=status.HTTP_400_BAD_REQUEST
                )

        print(f"\n[{'='*50}]")
        print(f"DEBUG: Triggering Test Notification")
        print(f"DEBUG: Target Email: {target_email}")
        print(f"DEBUG: Using Token: {actual_token[:40]}... (length: {len(actual_token)})")
        
        # Import the helper we already have
        from chat.notifications import send_fcm_notification
        
        fcm_response = send_fcm_notification(
            token=actual_token,
            title=title,
            body=body,
            data={"type": "test_notification"},
            user_id=target_user_id
        )

        print(f"DEBUG: Final FCM Response: {fcm_response}")
        print(f"[{'='*50}]\n")

        return Response({
            "success": True, 
            "message": f"Push notification triggered for {target_email}.",
            "fcm_response": fcm_response
        }, status=status.HTTP_200_OK)


from .serializers import NotificationHistorySerializer
from .models import NotificationHistory
from core.pagination import paginate_queryset

from django.utils import timezone
from datetime import timedelta

class NotificationHistoryAPIView(APIView):
    """
    GET /api/auth/notifications/
    Fetch notification history for the authenticated user.
    Automatically deletes history older than 60 days.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # ── 60-Day Retention Policy: Delete older records first ──
        cutoff_date = timezone.now() - timedelta(days=60)
        NotificationHistory.objects.filter(user=request.user, created_at__lt=cutoff_date).delete()

        # ── Fetch the remaining valid history ──
        qs = NotificationHistory.objects.filter(user=request.user)
        return paginate_queryset(qs, request, NotificationHistorySerializer)

    def patch(self, request):
        """
        PATCH /api/auth/notifications/
        Mark all unread notifications as read.
        """
        updated = NotificationHistory.objects.filter(user=request.user, is_read=False).update(is_read=True)
        return Response({
            "success": True,
            "message": f"Marked {updated} notifications as read."
        }, status=status.HTTP_200_OK)

class PopupNotificationAPIView(APIView):
    """
    GET /api/auth/notifications/popup/
    Returns the latest unread notifications to show as a popup on app open.
    Does NOT mark them as read — that happens explicitly via POST when the
    popup is dismissed, so a crash/early-close doesn't silently lose them.

    Query params:
        limit (optional, default 5) — max notifications to return.

    POST /api/auth/notifications/popup/
    Marks the given notification(s) as read (called when the popup is closed).
    Body: { "ids": ["uuid1", "uuid2", ...] }
    If "ids" is omitted, marks ALL currently unread notifications as read.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # try:
        #     limit = int(request.query_params.get('limit', 5))
        # except (TypeError, ValueError):
        #     limit = 5
        # limit = max(1, min(limit, 50))  # sane bounds

        unread_qs = NotificationHistory.objects.filter(user=request.user, is_read=False)
        total_unread = unread_qs.count()
        # notifications = list(unread_qs.order_by('-created_at')[:limit])
        notifications = list(unread_qs.order_by('-created_at'))

        serializer = NotificationHistorySerializer(notifications, many=True)
        return Response({
            "success": True,
            "total_unread": total_unread,
            "data": serializer.data,
        }, status=status.HTTP_200_OK)

    def post(self, request):
        ids = request.data.get('ids')

        qs = NotificationHistory.objects.filter(user=request.user, is_read=False)
        if ids:
            qs = qs.filter(id__in=ids)

        updated = qs.update(is_read=True)
        return Response({
            "success": True,
            "message": f"Marked {updated} notification(s) as read.",
        }, status=status.HTTP_200_OK)