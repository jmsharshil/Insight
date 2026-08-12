from django.conf import settings
from urllib.parse import urlencode
import secrets
import string
from core.sender import send_email
from chat.notifications import send_whatsapp_text

def generate_temporary_password(length=12):
    """Generate a secure temporary password"""
    characters = string.ascii_letters + string.digits + "!@#$%^&*"
    password = ''.join(secrets.choice(characters) for _ in range(length))
    return password


def send_password_set_email(user, token):
    base_url = getattr(settings, 'FRONTEND_BASE_URL', 'http://localhost:5173')
    query = urlencode({'token': token})
    password_set_link = f"{base_url}/api/auth/set-password?{query}"

    subject = f"Set your {user.organization.name if user.organization else 'Insight ERP'} password"
    text_content = f"""
Hello {user.name},

An account has been created for you in the {user.organization.name if user.organization else 'Insight ERP'} System.

To set your password and activate your account, please use the secure link below:

{password_set_link}

This link is valid for a limited time and can only be used once.

If you did not request this account, please ignore this email.

Thank you,
{user.organization.name if user.organization else 'Insight ERP'} Team
"""

    send_email(
        to=user.email,
        subject=subject,
        text=text_content,
        template='emails/password_set.html',
        template_context={
            'user_name': user.name,
            'password_set_link': password_set_link,
        },
        organization=user.organization,
    )

    try:
        send_whatsapp_text(to=user.phone,body=text_content,user_id=str(user.id))
    except Exception as e:
        print(e)


def send_otp_email(user, otp):
    subject = "Your OTP Verification Code"
    text_content = f"""
Hello {user.name},

Welcome to {user.organization.name if user.organization else 'Insight ERP'} System.

We received a request to verify your account. Please use the One-Time Password (OTP) below to complete your verification process:

OTP Code: {otp}

This OTP is valid for the next 5 minutes.

Once verified, you will be able to securely access your account and continue using the platform.

Thank you for choosing {user.organization.name if user.organization else 'Insight ERP'} System.

Best Regards,
{user.organization.name if user.organization else 'Insight ERP'} Team
"""

    send_email(
        to=user.email,
        subject=subject,
        text=text_content,
        template='emails/otp.html',
        template_context={
            'user_name': user.name,
            'otp_code': otp,
        },
        organization=user.organization,
    )

    try:
        send_whatsapp_text(to=user.phone,body=text_content,user_id=str(user.id))
    except Exception as e:
        print(e)


def send_student_login_credentials(user, password):
    """Send login credentials to newly converted student"""
    subject = "Welcome! Your Student Account Login Credentials"
    text_content = f"""
Hello {user.name},

Congratulations! Your account has been successfully created in the {user.organization.name if user.organization else 'Insight ERP'} System.

Your Login Credentials:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Email/Username: {user.email}
Password: {password}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

How to Access Your Account:
1. Visit the {user.organization.name if user.organization else 'Insight ERP'} System login page
2. Enter your email/username and the password provided above
3. Log in to your student dashboard

Important Security Notes:
• Please keep your credentials confidential
• Change your password after your first login
• Never share your password with anyone
• If you did not request this account, please contact our support team

Welcome to {user.organization.name if user.organization else 'Insight ERP'}!

Best Regards,
{user.organization.name if user.organization else 'Insight ERP'} Team
"""

    send_email(
        to=user.email,
        subject=subject,
        text=text_content,
        template='emails/student_credentials.html',
        template_context={
            'user_name': user.name,
            'user_email': user.email,
            'password': password,
        },
        organization=user.organization,
    )

    try:
        send_whatsapp_text(to=user.phone,body=text_content,user_id=str(user.id))
    except Exception as e:
        print(e)


def send_parent_login_credentials(parent_user, student_user, password):
    """Send login credentials to a parent account linked with a student"""
    subject = "Welcome! Your Parent Portal Login Credentials"
    text_content = f"""
Hello {parent_user.name},

Your parent account has been created in the {parent_user.organization.name if parent_user.organization else 'Insight ERP'} System.

Linked Student Profile:
Student Name: {student_user.name}
Student Email: {student_user.email}

Your Login Credentials:
Email/Username: {parent_user.email}
Password: {password}

How to Access Your Account:
1. Visit the {parent_user.organization.name if parent_user.organization else 'Insight ERP'} System login page
2. Enter your email/username and the password provided above
3. Log in to view your linked student's profile and updates

Important Security Notes:
- Please keep your credentials confidential
- Change your password after your first login
- Never share your password with anyone

Best Regards,
{parent_user.organization.name if parent_user.organization else 'Insight ERP'} Team
"""

    send_email(
        to=parent_user.email,
        subject=subject,
        text=text_content,
        template='emails/parent_credentials.html',
        template_context={
            'parent_name': parent_user.name,
            'student_name': student_user.name,
            'student_email': student_user.email,
            'parent_email': parent_user.email,
            'password': password,
        },
        organization=parent_user.organization,
    )
    
    try:
        send_whatsapp_text(to=parent_user.phone,body=text_content,parent_id=str(parent_user.id))
    except Exception as e:
        print(e)

def send_login_otp(user, otp):
    subject = "Your Login Verification Code"
    text_content = f"""
Hello {user.name},

A login attempt was made on your {user.organization.name if user.organization else 'Insight ERP'} account.

Verification Code: {otp}

This code is valid for the next 10 minutes. If this wasn't you, please change your password immediately.

Best Regards,
{user.organization.name if user.organization else 'Insight ERP'} Team
"""

    send_email(
        to=user.email,
        subject=subject,
        text=text_content,
        template='emails/login_otp.html',
        template_context={'user_name': user.name, 'otp_code': otp, 'organization_name':user.organization.name},
        organization=user.organization,
    )

    try:
        send_whatsapp_text(to=user.phone, body=text_content, user_id=str(user.id))
    except Exception as e:
        print(e)

def send_login_otp_resend(user, otp):
    subject = "Your New Login Verification Code"
    text_content = f"""
Hello {user.name},

As requested, here is your new login verification code for your {user.organization.name if user.organization else 'Insight ERP'} account.

Verification Code: {otp}

This code is valid for the next 10 minutes. Your previous code is no longer valid.

If you did not request this, please change your password immediately.

Best Regards,
{user.organization.name if user.organization else 'Insight ERP'} Team
"""

    send_email(
        to=user.email,
        subject=subject,
        text=text_content,
        template='emails/resend_login_otp.html',
        template_context={
            'user_name': user.name,
            'otp_code': otp,
            'organization': user.organization,
            "organization_name": user.organization.name
        },
        organization=user.organization,
    )

    try:
        send_whatsapp_text(to=user.phone, body=text_content, user_id=str(user.id))
    except Exception as e:
        print(e)


def generate_username(role, branch=None, course=None, batch_attempt=None, attempt_year=None):
    from django.utils import timezone
    from auth_user.models import User
    
    institute = "IIPS"
    
    ROLE_ABBR = {
        'super_admin': 'SA',
        'branch_manager': 'BM',
        'admin_senior_executive': 'ASE',
        'admin_executive': 'AE',
        'front_desk': 'FD',
        'counsellor': 'CO',
        'sales_senior_executive': 'SSE',
        'sales_executive': 'SE',
        'tele_caller': 'TC',
        'exam_supervisor': 'ES',
        'paper_checker': 'PC',
        'accountant': 'AC',
        'faculty': 'FA',
        'house_keeping': 'HK',
        'security': 'SC',
        'student': 'S',
        'parents': 'P',
        'parent': 'P'
    }
    role_str = ROLE_ABBR.get(role, role[:2].upper())
    
    if role == 'super_admin':
        prefix = f"{institute}_{role_str}_"
    else:
        branch_str = "XX"
        if branch and getattr(branch, 'name', None):
            branch_str = branch.name[:2].upper()
            
        if role in ['student', 'parents', 'parent']:
            course_str = (course or 'UNKNOWN').upper()
            
            attempt_char = (batch_attempt[0].upper() if batch_attempt else 'X')
            year_str = str(attempt_year)[-2:] if attempt_year else str(timezone.now().year)[-2:]
            attempt_str = f"{attempt_char}{year_str}"
            
            prefix = f"{institute}_{branch_str}_{role_str}_{course_str}_{attempt_str}_"
        else:
            prefix = f"{institute}_{branch_str}_{role_str}_"
            
    last_user = User.objects.filter(username__startswith=prefix).order_by('-username').first()
    if last_user and last_user.username:
        try:
            seq = int(last_user.username.split('_')[-1]) + 1
        except ValueError:
            seq = 1
    else:
        seq = 1
            
    return f"{prefix}{seq:04d}", seq