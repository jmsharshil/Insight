from django.core.mail import send_mail
import secrets
import string


def generate_temporary_password(length=12):
    """Generate a secure temporary password"""
    characters = string.ascii_letters + string.digits + "!@#$%^&*"
    password = ''.join(secrets.choice(characters) for _ in range(length))
    return password


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


def send_student_login_credentials(user, password):
    """Send login credentials to newly converted student"""
    subject = "Welcome! Your Student Account Login Credentials"

    message = f"""
Hello {user.name},

Congratulations! Your account has been successfully created in the Insight ERP System.

Your Login Credentials:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Email/Username: {user.email}
Password: {password}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

How to Access Your Account:
1. Visit the Insight ERP System login page
2. Enter your email/username and the password provided above
3. Log in to your student dashboard

Important Security Notes:
• Please keep your credentials confidential
• Change your password after your first login
• Never share your password with anyone
• If you did not request this account, please contact our support team

Need Help?
If you have any questions or encounter any issues, please contact our support team at support@insighterpssystem.com

Welcome to Insight!

Best Regards,
Insight ERP Team
"""

    send_mail(
        subject=subject,
        message=message,
        from_email=None,
        recipient_list=[user.email],
        fail_silently=False
    )


def send_parent_login_credentials(parent_user, student_user, password):
    """Send login credentials to a parent account linked with a student"""
    subject = "Welcome! Your Parent Portal Login Credentials"

    message = f"""
Hello {parent_user.name},

Your parent account has been created in the Insight ERP System.

Linked Student Profile:
Student Name: {student_user.name}
Student Email: {student_user.email}

Your Login Credentials:
Email/Username: {parent_user.email}
Password: {password}

How to Access Your Account:
1. Visit the Insight ERP System login page
2. Enter your email/username and the password provided above
3. Log in to view your linked student's profile and updates

Important Security Notes:
- Please keep your credentials confidential
- Change your password after your first login
- Never share your password with anyone

Best Regards,
Insight ERP Team
"""

    send_mail(
        subject=subject,
        message=message,
        from_email=None,
        recipient_list=[parent_user.email],
        fail_silently=False,
    )