from django.core.mail import send_mail


def send_otp_email(user, otp):

    subject = "Your OTP Verification Code"

    message = f"""
Hello {user.name},

Welcome to Insight ERP System.

We received a request to verify your account. Please use the One-Time Password (OTP) below to complete your verification process:

OTP Code: {otp}

This OTP is valid for the next 5 minutes.

Once verified, you will be able to securely access your account and continue using the platform.

Thank you for choosing Insight ERP System.

Best Regards,
Insight ERP Team
"""

    send_mail(subject=subject,message=message,from_email=None,recipient_list=[user.email],
        fail_silently=False
    )