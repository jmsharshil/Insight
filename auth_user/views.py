from django.shortcuts import render

# Create your views here.
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import User
from .serializers import RegisterSerializer,LoginSerializer,VerifyOTPSerializer,ForgotPasswordSerializer,ResetPasswordSerializer
from .models import EmailOTP
from .utils import send_otp_email
from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import RefreshToken

class RegisterAPIView(APIView):
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

    def post(self, request):

        serializer = VerifyOTPSerializer(data=request.data)

        if serializer.is_valid():
            email = serializer.validated_data['email']
            otp = serializer.validated_data['otp']

            try:
                user = User.objects.get(email=email)
                otp_obj = EmailOTP.objects.filter(user=user,otp=otp,is_verified=False).last()

                if not otp_obj:
                    return Response({"error": "Invalid OTP"}, status=400)

                if otp_obj.is_expired():
                    return Response({"error": "OTP expired"}, status=400)

                otp_obj.is_verified = True
                otp_obj.save()

                user.is_active = True
                user.save()
                return Response({"message": "Account verified successfully"})
            except User.DoesNotExist:
                return Response({"error": "User not found"}, status=404)

        return Response(serializer.errors,status=400)
        
class LoginAPIView(APIView):

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data['email']
            password = serializer.validated_data['password']
            user = authenticate(request,email=email,password=password)
            if user is None:
                return Response({
                    "error": "Invalid credentials"
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
                }
            })
        return Response(
            serializer.errors,
            status=400
        )
    

class ForgotPasswordAPIView(APIView):

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)

        if serializer.is_valid():
            email = serializer.validated_data['email']
            try:
                user = User.objects.get(email=email)
                otp = EmailOTP.generate_otp()
                EmailOTP.objects.create(user=user,otp=otp)
                send_otp_email(user, otp)
                return Response({"message": "OTP sent successfully"})

            except User.DoesNotExist:
                return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)

        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )
    
class ResetPasswordAPIView(APIView):

    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)

        if serializer.is_valid():
            email = serializer.validated_data['email']
            otp = serializer.validated_data['otp']
            password = serializer.validated_data['password']
            try:
                user = User.objects.get(email=email)
                otp_obj = EmailOTP.objects.filter(user=user,otp=otp,is_verified=False).last()

                if not otp_obj:
                    return Response({"error": "Invalid OTP"}, status=status.HTTP_400_BAD_REQUEST)

                if otp_obj.is_expired():
                    return Response({"error": "OTP expired"}, status=status.HTTP_400_BAD_REQUEST)

                otp_obj.is_verified = True
                otp_obj.save()

                user.set_password(password)
                user.save()

                return Response({"message": "Password reset successful"})

            except User.DoesNotExist:
                return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)

        return Response(serializer.errors,status=status.HTTP_400_BAD_REQUEST)