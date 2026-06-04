from django.shortcuts import render
from core.pagination import paginate_queryset
from django.db.models import Q

# Create your views here.
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
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
)
from .utils import send_otp_email, send_password_set_email
from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import RefreshToken
from leads.models import Lead
from leads.serializers import LeadDetailSerializer

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
                return Response({
                    "error": "Account is not verified"
                }, status=400)
            refresh = RefreshToken.for_user(user)
            return Response({
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
                    "organization": str(user.organization.id) if user.organization else None,
                    "organization_name": user.organization.name if user.organization else None,
                    "linked_student": {
                        "id": str(user.linked_student.id),
                        "name": user.linked_student.name,
                        "email": user.linked_student.email,
                    } if user.linked_student else None,
                }
            })
        return Response(
            serializer.errors,
            status=400
        )


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
            user = serializer.save()
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

class ParentStudentProfileAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        parent_user = request.user

        if parent_user.role != 'parents':
            return Response(
                {"success": False, "message": "Only parent users can access this endpoint."},
                status=status.HTTP_403_FORBIDDEN,
            )

        student_user = parent_user.linked_student
        if not student_user:
            return Response(
                {"success": False, "message": "No student is linked to this parent account."},
                status=status.HTTP_404_NOT_FOUND,
            )

        lead = Lead.objects.filter(email__iexact=student_user.email).order_by('-created_at').first()
        if not lead:
            lead = Lead.objects.filter(phone_student=student_user.phone).order_by('-created_at').first()

        student_data = {
            "id": str(student_user.id),
            "username": student_user.username,
            "email": student_user.email,
            "phone": student_user.phone,
            "name": student_user.name,
            "role": student_user.role,
        }

        return Response(
            {
                "success": True,
                "data": {
                    "parent": {
                        "id": str(parent_user.id),
                        "email": parent_user.email,
                        "name": parent_user.name,
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
    permission_classes = [IsAuthenticated]

    def delete(self, request, user_id):
        user = get_object_or_404(User, id=user_id, organization=request.user.organization)

        user.delete()

        return Response({
            "success": True,
            "message": "User deleted successfully"
        })

class UserListAPIView(APIView):
    # permission_classes = [IsAuthenticated]

    def get(self, request):
        users = User.objects.filter(organization=request.user.organization).order_by('-created_at')
        role = self.request.query_params.get('role')
        is_active = self.request.query_params.get('is_active')
        search = self.request.query_params.get('search')

        if search:
            users = users.filter(
                Q(name__icontains=search) |
                Q(email__icontains=search) |
                Q(phone__icontains=search)
            )
        if role:
            users = users.filter(role=role)
        if is_active:
            users = users.filter(is_active=is_active.lower() == 'true')
        
        return paginate_queryset(users, request, UserListSerializer)

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