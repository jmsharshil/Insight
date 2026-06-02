from django.shortcuts import render
from core.pagination import paginate_queryset

# Create your views here.
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework_simplejwt.authentication import JWTAuthentication
from .models import User
from .serializers import RegisterSerializer,LoginSerializer,VerifyOTPSerializer,ForgotPasswordSerializer,ResetPasswordSerializer,ChangePasswordSerializer, UserSerializer, UpdateUserSerializer
from .models import EmailOTP
from .utils import send_otp_email
from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import RefreshToken
from leads.models import Lead
from leads.serializers import LeadDetailSerializer

class RegisterAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
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
            users = User.objects.filter(email=email)
            user = None
            for candidate in users:
                candidate_user = authenticate(request, username=candidate.username, password=password)
                if candidate_user is not None:
                    user = candidate_user
                    break

            user_obj = User.objects.filter(email=email).first()
            if not user_obj:
                return Response({
                    "error": "User not found with this email"
                }, status=400)
            user = authenticate(request, username=user_obj.username, password=password)
            if user is None:
                return Response({
                    "error": "Incorrect password"
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
    permission_classes = [AllowAny]

    def get_user(self, user_id):
        return get_object_or_404(User, id=user_id)

    def get(self, request, user_id):
        user = self.get_user(user_id)
        serializer = UserSerializer(user)
        return Response(serializer.data)

    def put(self, request, user_id):
        user = self.get_user(user_id)

        serializer = UpdateUserSerializer(
            user,
            data=request.data
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
        user = self.get_user(user_id)

        serializer = UpdateUserSerializer(
            user,
            data=request.data,
            partial=True
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
        user = get_object_or_404(User, id=user_id)

        user.delete()

        return Response({
            "success": True,
            "message": "User deleted successfully"
        })

class UserListAPIView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        users = User.objects.all().order_by('-created_at')
        return paginate_queryset(users, request, UserSerializer)
