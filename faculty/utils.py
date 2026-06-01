import logging
from django.core.files.base import ContentFile

logger = logging.getLogger(__name__)


def generate_employee_id(branch):
    """Auto-generate: EMP-{BRANCH_CODE}-{seq}"""
    from .models import FacultyProfile
    code = getattr(branch, 'code', None) or str(branch.id)[:4].upper()
    count = FacultyProfile.objects.filter(branch=branch).count() + 1
    return f"EMP-{code}-{str(count).zfill(4)}"


def generate_faculty_qr_code(employee_id):
    """Generate QR code PNG and return ContentFile."""
    try:
        import qrcode
        from io import BytesIO
        qr = qrcode.make(employee_id)
        buf = BytesIO()
        qr.save(buf, format='PNG')
        buf.seek(0)
        return ContentFile(buf.read(), name=f'{employee_id}.png')
    except ImportError:
        logger.warning("qrcode library not installed — skipping QR generation.")
        return None
