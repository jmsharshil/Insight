"""
auth_user/permissions.py

Role-Based Access Control (RBAC) for the Insight ERP.

This module defines:
  1. ROLE_PERMISSIONS — static mapping of each role to its default modules
     and global privilege flags (canDelete, canExport).
  2. URL_MODULE_MAP — maps URL path prefixes to logical module names so the
     middleware can resolve which module a request targets.
  3. RoleModulePermission — DRF permission class for use in individual views.
  4. RBACMiddleware — Django middleware that enforces module access and
     global DELETE/export restrictions on every request.

Design decisions
────────────────
• The `settings` module is always accessible — every role needs it.
• `notifications` is always accessible because notification history is
  a global feature.
• Auth endpoints (login, register, OTP, etc.) are public and bypassed.
• The middleware only activates for authenticated users; anonymous requests
  pass through to DRF's own authentication layer.
• `dashboard` and `reports` are defined but currently NOT in any role's
  default modules — ready for future use.
"""

import re

# ═══════════════════════════════════════════════════════════════════════════════
# 1. ROLE → MODULE PERMISSIONS MATRIX
# ═══════════════════════════════════════════════════════════════════════════════

ROLE_PERMISSIONS = {
    'super_admin': {
        'default_modules': [
            'crm', 'students', 'courses_batches', 'timetable', 'attendance',
            'fees', 'exams', 'results', 'faculty', 'leave', 'chat',
            'inventory', 'notifications', 'audit_logs', 'payroll',
            'settings', 'users',
        ],
        'canDelete': True,
        'canExport': True,
    },
    'branch_manager': {
        'default_modules': [
            'crm', 'students', 'courses_batches', 'timetable', 'attendance',
            'fees', 'exams', 'results', 'faculty', 'payroll', 'leave',
            'chat', 'notifications', 'audit_logs', 'settings',
        ],
        'canDelete': False,
        'canExport': True,
    },
    'admin_senior_executive': {
        'default_modules': [
            'crm', 'students', 'courses_batches', 'timetable', 'attendance',
            'fees', 'exams', 'results', 'leave', 'chat', 'notifications',
            'payroll', 'settings',
        ],
        'canDelete': False,
        'canExport': True,
    },
    'admin_executive': {
        'default_modules': [
            'students', 'attendance', 'courses_batches', 'timetable',
            'payroll', 'settings', 'notifications', 'leave',
        ],
        'canDelete': False,
        'canExport': False,
    },
    'front_desk': {
        'default_modules': ['crm', 'payroll', 'settings', 'attendance', 'notifications', 'leave'],
        'canDelete': False,
        'canExport': False,
    },
    'counsellor': {
        'default_modules': ['crm', 'students', 'payroll', 'settings', 'attendance', 'notifications', 'leave'],
        'canDelete': False,
        'canExport': False,
    },
    'tele_caller': {
        'default_modules': ['crm', 'payroll', 'settings', 'attendance', 'notifications', 'leave'],
        'canDelete': False,
        'canExport': False,
    },
    'sales_senior_executive': {
        'default_modules': ['crm', 'payroll', 'settings', 'attendance', 'notifications', 'leave'],
        'canDelete': False,
        'canExport': True,
    },
    'sales_executive': {
        'default_modules': ['crm', 'payroll', 'settings', 'attendance', 'notifications', 'leave'],
        'canDelete': False,
        'canExport': False,
    },
    'student': {
        'default_modules': [
            'timetable', 'attendance', 'courses_batches', 'exams', 'fees',
            'leave', 'chat', 'notifications', 'settings',
        ],
        'canDelete': False,
        'canExport': False,
    },
    'parents': {
        'default_modules': [
            'timetable', 'attendance', 'courses_batches', 'fees', 'exams',
            'leave', 'chat', 'notifications', 'settings',
        ],
        'canDelete': False,
        'canExport': False,
    },
    'faculty': {
        'default_modules': [
            'timetable', 'attendance', 'exams', 'leave', 'chat',
            'notifications', 'payroll', 'settings',
        ],
        'canDelete': False,
        'canExport': False,
    },
    'exam_supervisor': {
        'default_modules': [
            'attendance', 'exams', 'notifications', 'payroll', 'settings', 'leave',
        ],
        'canDelete': False,
        'canExport': False,
    },
    'paper_checker': {
        'default_modules': [
            'exams', 'notifications', 'payroll', 'settings', 'leave',
        ],
        'canDelete': False,
        'canExport': False,
    },
    'accountant': {
        'default_modules': [
            'attendance', 'fees', 'payroll', 'notifications', 'settings', 'leave',
        ],
        'canDelete': False,
        'canExport': True,
    },
    'security': {
        'default_modules': [
            'attendance', 'payroll', 'leave', 'chat', 'notifications',
            'settings',
        ],
        'canDelete': False,
        'canExport': False,
    },
    'house_keeping': {
        'default_modules': [
            'attendance', 'payroll', 'leave', 'chat', 'notifications',
            'settings',
        ],
        'canDelete': False,
        'canExport': False,
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
# 2. URL PREFIX → MODULE MAP
#    Order matters: first match wins. More specific prefixes go first.
# ═══════════════════════════════════════════════════════════════════════════════

URL_MODULE_MAP = [
    # Auth endpoints — always allowed (handled by bypass list)
    # CRM / Leads
    (r'^api/v1/leads/', 'crm'),
    (r'^api/v1/admissions/', 'crm'),
    # Students
    (r'^api/v1/students/', 'students'),
    # Courses & Batches
    (r'^api/v1/courses/', 'courses_batches'),
    (r'^api/v1/subjects/', 'courses_batches'),
    (r'^api/v1/batches/', 'courses_batches'),
    (r'^api/v1/classrooms/', 'courses_batches'),
    (r'^api/v1/chapters/', 'courses_batches'),
    (r'^api/v1/levels/', 'courses_batches'),
    # Timetable
    (r'^api/v1/timetable/', 'timetable'),
    # Attendance
    (r'^api/v1/attendance/', 'attendance'),
    (r'^api/v1/qr-scan/', 'attendance'),
    (r'^api/v1/employee-attendance/', 'attendance'),
    (r'^api/v1/batch-qr/', 'attendance'),
    # Fees
    (r'^api/v1/fees/', 'fees'),
    (r'^api/v1/fee-structures/', 'fees'),
    (r'^api/v1/installment/', 'fees'),
    (r'^api/v1/payments/', 'fees'),
    # Exams
    (r'^api/v1/exams/', 'exams'),
    (r'^api/v1/questions/', 'exams'),
    (r'^api/v1/seating/', 'exams'),
    # Results (part of exams module)
    (r'^api/v1/results/', 'results'),
    (r'^api/v1/papers/', 'results'),
    (r'^api/v1/checker/', 'results'),
    (r'^api/v1/marksheets/', 'results'),
    # Faculty
    (r'^api/v1/faculty/', 'faculty'),
    (r'^api/v1/sessions/', 'faculty'),
    # Payroll
    (r'^api/v1/payroll/', 'payroll'),
    # Leave
    (r'^api/v1/leave/', 'leave'),
    (r'^api/v1/late-entry/', 'leave'),
    # Chat
    (r'^api/v1/chat/', 'chat'),
    # Inventory
    (r'^api/v1/inventory/', 'inventory'),
    # Notifications (always allowed, but mapping exists for completeness)
    (r'^api/auth/notifications/', 'notifications'),
    (r'^api/auth/fcm-token/', 'notifications'),
    # Audit Logs
    (r'^api/audit-logs/', 'audit_logs'),
    # Reports
    (r'^api/v1/reports/', 'reports'),
    # Dashboard
    (r'^api/v1/dashboard/', 'dashboard'),
    # Branch management (settings module)
    (r'^api/v1/branches/', 'settings'),
    # Scheduler (settings / internal)
    (r'^api/v1/scheduler/', 'settings'),
    # Core dropdowns (always allowed — settings)
    (r'^api/v1/dropdowns/', 'settings'),
    # Users management
    (r'^api/auth/users/', 'users'),
    (r'^api/auth/user/', 'users'),
    (r'^api/auth/add-user/', 'users'),
]

# Paths that are always allowed regardless of role/module
BYPASS_PATHS = [
    r'^api/auth/login',
    r'^api/auth/register',
    r'^api/auth/verify-otp',
    r'^api/auth/forgot-password',
    r'^api/auth/reset-password',
    r'^api/auth/set-password',
    r'^api/auth/change-password',
    r'^api/auth/profile',
    r'^api/auth/organization',
    r'^api/auth/token/refresh',
    r'^api/auth/fcm-token',
    r'^api/auth/notifications',
    r'^api/auth/test-notification',
    r'^api/auth/toggle-status',
    r'^api/v1/dropdowns/',
    r'^admin/',
    r'^media/',
    r'^static/',
]


def resolve_module_for_path(path):
    """Return the logical module name for a given URL path, or None."""
    for pattern, module in URL_MODULE_MAP:
        if re.match(pattern, path):
            return module
    return None


def is_bypass_path(path):
    """Return True if the path should skip RBAC checks."""
    for pattern in BYPASS_PATHS:
        if re.match(pattern, path):
            return True
    return False


def get_role_config(role):
    """Return the permissions dict for a role, with safe defaults."""
    return ROLE_PERMISSIONS.get(role, {
        'default_modules': ['settings'],
        'canDelete': False,
        'canExport': False,
    })


def get_user_modules(user):
    """
    Return the set of modules a user can access.
    Uses accessible_modules from the user object if set, otherwise falls back to default_modules from ROLE_PERMISSIONS.
    """
    if hasattr(user, 'accessible_modules') and user.accessible_modules is not None:
        return set(user.accessible_modules)
        
    config = get_role_config(getattr(user, 'role', ''))
    modules = set(config.get('default_modules', []))
    return modules


def can_user_delete(user):
    """Return True if the user's role allows DELETE operations."""
    config = get_role_config(getattr(user, 'role', ''))
    return config.get('canDelete', False)


def can_user_export(user):
    """Return True if the user's role allows export operations."""
    config = get_role_config(getattr(user, 'role', ''))
    return config.get('canExport', False)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. DRF PERMISSION CLASSES
# ═══════════════════════════════════════════════════════════════════════════════

from rest_framework.permissions import BasePermission


class RoleModulePermission(BasePermission):
    """
    DRF permission that checks the requesting user's role has access
    to the module associated with the current URL.

    Usage in a view:
        permission_classes = [IsAuthenticated, RoleModulePermission]

    You can also set `rbac_module` on the view to override auto-detection:
        class MyView(APIView):
            rbac_module = 'payroll'
    """
    message = 'You do not have permission to access this module.'

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        # Super admin always has access
        if getattr(user, 'role', '') == 'super_admin':
            return True

        # Check DELETE restriction
        if request.method == 'DELETE' and not can_user_delete(user):
            self.message = 'Your role does not allow delete operations.'
            return False

        # Resolve module
        module = getattr(view, 'rbac_module', None)
        if not module:
            module = resolve_module_for_path(request.path)
        if not module:
            return True  # unknown module — let DRF handle it

        return module in get_user_modules(user)


class CanDeletePermission(BasePermission):
    """Block DELETE requests for roles where canDelete is False."""
    message = 'Your role does not allow delete operations.'

    def has_permission(self, request, view):
        if request.method != 'DELETE':
            return True
        user = request.user
        if not user or not user.is_authenticated:
            return False
        return can_user_delete(user)


class CanExportPermission(BasePermission):
    """Block export actions for roles where canExport is False."""
    message = 'Your role does not allow export operations.'

    def has_permission(self, request, view):
        # Check if this is an export request (query param or view attribute)
        is_export = (
            request.query_params.get('export') in ['true', '1', 'csv', 'excel', 'pdf']
            or getattr(view, 'is_export_view', False)
        )
        if not is_export:
            return True
        user = request.user
        if not user or not user.is_authenticated:
            return False
        return can_user_export(user)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. DJANGO MIDDLEWARE
# ═══════════════════════════════════════════════════════════════════════════════

from django.http import JsonResponse


class RBACMiddleware:
    """
    Django middleware that enforces RBAC on every request:
      1. Skips unauthenticated users (let DRF handle 401).
      2. Skips bypass paths (auth, admin, static, media).
      3. Resolves the target module from the URL.
      4. Checks the user's role has access to that module.
      5. Blocks DELETE for roles with canDelete=False.
      6. Blocks export requests for roles with canExport=False.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Only enforce on authenticated users
        user = getattr(request, 'user', None)
        if not user or not getattr(user, 'is_authenticated', False):
            return self.get_response(request)

        path = request.path.lstrip('/')

        # Skip bypass paths
        if is_bypass_path(path):
            return self.get_response(request)

        role = getattr(user, 'role', '')
        if not role:
            return self.get_response(request)

        # Super admin bypasses all checks
        if role == 'super_admin':
            return self.get_response(request)

        config = get_role_config(role)

        # ── Module access check ──
        module = resolve_module_for_path(path)
        if module:
            user_modules = get_user_modules(user)
            if module not in user_modules:
                return JsonResponse({
                    'success': False,
                    'message': f'Access denied. Your role ({role}) does not have access to the {module} module.',
                }, status=403)

        # ── Global DELETE restriction ──
        if request.method == 'DELETE' and not config.get('canDelete', False):
            return JsonResponse({
                'success': False,
                'message': 'Your role does not allow delete operations.',
            }, status=403)

        # ── Export restriction ──
        export_param = request.GET.get('export', '')
        if export_param in ('true', '1', 'csv', 'excel', 'pdf'):
            if not config.get('canExport', False):
                return JsonResponse({
                    'success': False,
                    'message': 'Your role does not allow export operations.',
                }, status=403)

        return self.get_response(request)
