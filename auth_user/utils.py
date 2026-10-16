from django.conf import settings
from urllib.parse import urlencode
import secrets
import string
from decimal import Decimal, ROUND_HALF_UP
from core.sender import send_email
from chat.notifications import send_whatsapp_with_fallback

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
        org_name = user.organization.name if user.organization else 'Insight ERP'
        send_whatsapp_with_fallback(
            to=user.phone,
            template_name="password_set_",
            language_code="en",
            components=[
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": user.name},
                        {"type": "text", "text": org_name},
                    ],
                },
                {
                    "type": "button",
                    "sub_type": "url",
                    "index": 0,
                    "parameters": [{"type": "text", "text": password_set_link}],
                }
            ],
            fallback_body=text_content,
            user_id=str(user.id),
        )
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

    # send_email(
    #     to=user.email,
    #     subject=subject,
    #     text=text_content,
    #     template='emails/otp.html',
    #     template_context={
    #         'user_name': user.name,
    #         'otp_code': otp,
    #     },
    #     organization=user.organization,
    # )

    try:
        send_whatsapp_with_fallback(
            to=user.phone,
            template_name="otp_verification",
            language_code="en",
            components=[
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": str(otp)}],
                },
                {
                    "type": "button",
                    "sub_type": "url",
                    "index": 0,
                    "parameters": [{"type": "text", "text": str(otp)}],
                }
            ],
            fallback_body=f"{otp} is your verification code. For your security, do not share this code.",
            user_id=str(user.id),
        )
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
        send_whatsapp_with_fallback(
            to=user.phone,
            template_name="admission_process",
            language_code="en",
            components=[
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": user.name},
                        {"type": "text", "text": user.organization.name if user.organization else 'Insight ERP'}
                    ],
                },
                {
                    "type": "button",
                    "sub_type": "url",
                    "index": 0,
                    "parameters": [{"type": "text", "text": "login"}],
                }
            ],
            fallback_body=text_content,
            user_id=str(user.id),
        )
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
        send_whatsapp_with_fallback(
            to=parent_user.phone,
            template_name="admission_process",
            language_code="en",
            components=[
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": parent_user.name},
                        {"type": "text", "text": parent_user.organization.name if parent_user.organization else 'Insight ERP'}
                    ],
                },
                {
                    "type": "button",
                    "sub_type": "url",
                    "index": 0,
                    "parameters": [{"type": "text", "text": "login"}],
                }
            ],
            fallback_body=text_content,
            user_id=str(parent_user.id),
        )
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

    # send_email(
    #     to=user.email,
    #     subject=subject,
    #     text=text_content,
    #     template='emails/login_otp.html',
    #     template_context={'user_name': user.name, 'otp_code': otp, 'organization_name':user.organization.name},
    #     organization=user.organization,
    # )

    try:
        send_whatsapp_with_fallback(
            to=user.phone,
            template_name="login_otp",
            language_code="en",
            components=[
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": str(otp)}],
                },
                {
                    "type": "button",
                    "sub_type": "url",
                    "index": 0,
                    "parameters": [{"type": "text", "text": str(otp)}],
                }
            ],
            fallback_body=f"{otp} is your verification code. For your security, do not share this code.",
            user_id=str(user.id),
        )
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

    # send_email(
    #     to=user.email,
    #     subject=subject,
    #     text=text_content,
    #     template='emails/resend_login_otp.html',
    #     template_context={
    #         'user_name': user.name,
    #         'otp_code': otp,
    #         'organization': user.organization,
    #         "organization_name": user.organization.name
    #     },
    #     organization=user.organization,
    # )

    try:
        send_whatsapp_with_fallback(
            to=user.phone,
            template_name="resend_login_otp",
            language_code="en",
            components=[
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": str(otp)}],
                },
                {
                    "type": "button",
                    "sub_type": "url",
                    "index": 0,
                    "parameters": [{"type": "text", "text": str(otp)}],
                }
            ],
            fallback_body=f"{otp} is your verification code. For your security, do not share this code.",
            user_id=str(user.id),
        )
    except Exception as e:
        print(e)


def generate_username(role, branch=None, branches=None, course=None, batch_attempt=None, attempt_year=None):
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
        'head_coordinator': 'HC',
        'senior_tele_caller': 'STC',
        'cmo': 'CMO',
        'associate_bdm': 'ABDM',
        'printers': 'PR',
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
        branch_set = []
        if branch and getattr(branch, 'name', None):
            branch_set.append(branch)
        if branches:
            for b in branches:
                if getattr(b, 'name', None) and b not in branch_set:
                    branch_set.append(b)
                    
        branch_str = "XX"
        if branch_set:
            branch_names = [b.name[:2].upper() for b in branch_set]
            branch_str = "_".join(branch_names)
            
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


def calculate_working_hours(start_time, end_time):
    """
    Calculate working hours between start_time and end_time.
    Supports datetime.time, datetime.datetime, or string representations (e.g. '09:00', '17:30').
    Handles overnight shifts (end_time < start_time) by treating end_time as the next day.
    Returns Decimal with 2 decimal places.
    """
    if not start_time or not end_time:
        return Decimal('0.00')

    from datetime import datetime, date, time, timedelta

    def _parse_time(t):
        if not t:
            return None
        if isinstance(t, time):
            return t
        if isinstance(t, datetime):
            return t.time()
        if isinstance(t, str):
            t_str = t.strip()
            if not t_str:
                return None
            try:
                return time.fromisoformat(t_str)
            except (ValueError, AttributeError):
                pass
            for fmt in ('%H:%M:%S', '%H:%M', '%H:%M:%S.%f', '%I:%M %p', '%I:%M:%S %p'):
                try:
                    return datetime.strptime(t_str, fmt).time()
                except ValueError:
                    pass
        return None

    parsed_start = _parse_time(start_time)
    parsed_end = _parse_time(end_time)

    if not parsed_start or not parsed_end:
        return Decimal('0.00')

    dummy_date = date(2000, 1, 1)
    s_dt = datetime.combine(dummy_date, parsed_start)
    e_dt = datetime.combine(dummy_date, parsed_end)

    if e_dt < s_dt:
        e_dt += timedelta(days=1)

    diff_seconds = (e_dt - s_dt).total_seconds()
    hours = Decimal(str(diff_seconds)) / Decimal('3600')
    return hours.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


WEEKDAY_NAMES = [
    'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'
]

WEEKDAY_MAP = {
    0: 'monday',
    1: 'tuesday',
    2: 'wednesday',
    3: 'thursday',
    4: 'friday',
    5: 'saturday',
    6: 'sunday',
    'mon': 'monday',
    'monday': 'monday',
    'tue': 'tuesday',
    'tues': 'tuesday',
    'tuesday': 'tuesday',
    'wed': 'wednesday',
    'wednesday': 'wednesday',
    'thu': 'thursday',
    'thur': 'thursday',
    'thurs': 'thursday',
    'thursday': 'thursday',
    'fri': 'friday',
    'friday': 'friday',
    'sat': 'saturday',
    'saturday': 'saturday',
    'sun': 'sunday',
    'sunday': 'sunday',
}


def normalize_day_name(day_val):
    """
    Normalizes a day representation (int 0-6, string day name or abbreviation)
    to lowercase day name ('monday' .. 'sunday').
    """
    if day_val is None:
        return None
    if isinstance(day_val, int):
        return WEEKDAY_MAP.get(day_val)
    val_str = str(day_val).strip().lower()
    if val_str.isdigit():
        return WEEKDAY_MAP.get(int(val_str))
    return WEEKDAY_MAP.get(val_str, val_str)


def process_weekly_schedule(schedule_data):
    """
    Validates, normalizes, and auto-calculates working hours for a day-wise weekly schedule.
    
    Accepts:
      - dict: {'monday': {'start_time': '10:00', 'end_time': '19:00'}, 'tuesday': ...}
      - list: [{'day': 'monday', 'start_time': '10:00', 'end_time': '19:00'}, ...]
      - JSON string of the above
      
    For each day:
      - If start_time and end_time are present and working_hours is not explicitly provided (or 0),
        automatically computes working_hours between start_time and end_time.
      - If is_off is True, working_hours is set to 0.00.
      
    Returns:
      (normalized_schedule_dict, average_daily_hours)
    """
    if not schedule_data:
        return {}, Decimal('0.00')

    if isinstance(schedule_data, str):
        import json
        try:
            schedule_data = json.loads(schedule_data)
        except Exception:
            return {}, Decimal('0.00')

    normalized = {}
    day_entries = []

    if isinstance(schedule_data, dict):
        for k, v in schedule_data.items():
            if isinstance(v, dict):
                entry = dict(v)
                entry['day'] = k
                day_entries.append(entry)
    elif isinstance(schedule_data, (list, tuple)):
        for item in schedule_data:
            if isinstance(item, dict):
                day_entries.append(dict(item))

    active_working_hours = []

    for entry in day_entries:
        raw_day = entry.get('day')
        day_key = normalize_day_name(raw_day)
        if not day_key or day_key not in WEEKDAY_NAMES:
            continue

        start_time = entry.get('start_time')
        end_time = entry.get('end_time')
        raw_off = entry.get('is_off', False)
        if isinstance(raw_off, str):
            is_off = raw_off.strip().lower() in ('true', '1', 'yes', 't')
        else:
            is_off = bool(raw_off)
        raw_wh = entry.get('working_hours')

        def _fmt_time(t):
            if not t:
                return None
            if hasattr(t, 'strftime'):
                return t.strftime('%H:%M:%S')
            t_str = str(t).strip()
            return t_str if t_str else None

        clean_start = _fmt_time(start_time)
        clean_end = _fmt_time(end_time)

        wh_val = None
        if raw_wh not in [None, '', 'null', 'undefined']:
            try:
                wh_val = Decimal(str(raw_wh))
            except Exception:
                wh_val = None

        if wh_val is not None and wh_val > 0:
            calc_wh = wh_val
        elif clean_start and clean_end:
            calc_wh = calculate_working_hours(clean_start, clean_end)
        else:
            calc_wh = Decimal('0.00')

        if calc_wh > 0 and not is_off:
            active_working_hours.append(calc_wh)

        normalized[day_key] = {
            'start_time': clean_start,
            'end_time': clean_end,
            'working_hours': float(calc_wh),
            'is_off': is_off,
        }

    avg_hours = Decimal('0.00')
    if active_working_hours:
        avg_hours = (sum(active_working_hours) / Decimal(len(active_working_hours))).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )

    return normalized, avg_hours
