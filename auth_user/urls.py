from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import RegisterAPIView,VerifyOTPAPIView,LoginAPIView,ForgotPasswordAPIView,ResetPasswordAPIView,ParentStudentProfileAPIView,UpdateUserAPIView,DeleteUserAPIView,UserListAPIView,UserProfileAPIView

urlpatterns = [
    path('register/',RegisterAPIView.as_view(),name='register'),
    path('verify-otp/',VerifyOTPAPIView.as_view(),name='verify-otp'),
    path('login/',LoginAPIView.as_view(),name='login'),
    path('token/refresh/',TokenRefreshView.as_view(),name='refresh-token'),
    path('forgot-password/',ForgotPasswordAPIView.as_view(),name='forgot-password'),
    path('reset-password/',ResetPasswordAPIView.as_view(),name='reset-password'),
    # path('parent/student-profile/', ParentStudentProfileAPIView.as_view(), name='parent-student-profile'),
    path('users/<uuid:user_id>/',UpdateUserAPIView.as_view(),name='update-user'),
    path('users/<uuid:user_id>/delete/',DeleteUserAPIView.as_view(),name='delete-user'),
    path('users/', UserListAPIView.as_view(), name='users-list'),
    path('me/', UserProfileAPIView.as_view(), name='user-profile'),
]

