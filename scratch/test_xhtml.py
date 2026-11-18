import os
import sys
from pathlib import Path
from decimal import Decimal
import uuid
from io import BytesIO

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# Mock settings
import django
from django.conf import settings
if not settings.configured:
    settings.configure(
        BASE_DIR=BASE_DIR,
        TEMPLATES=[{
            'BACKEND': 'django.template.backends.django.DjangoTemplates',
            'DIRS': [BASE_DIR / 'templates'],
            'APP_DIRS': False,
        }],
        INSTALLED_APPS=[]
    )
    django.setup()

from django.template.loader import get_template
template = get_template('fees/receipt.html')

context = {
    'receipt_no': 'REC-TEST-001',
    'receipt_date': '17 Nov, 2026',
    'student_name': 'Test Student',
    'amount': '₹12,500.00',
    'amount_words': 'Twelve Thousand Five Hundred Rupees',
    'batch_name': 'CSEET Nov 2026',
    'payment_type': 'token',
    'payment_mode': 'cash',
    'transaction_ref': 'CASH-123',
    'transaction_date': '17 Nov, 2026',
    'logo_url': 'https://insightsinstitutes.blob.core.windows.net/media/insight.png',
    'signature_url': 'https://insightsinstitutes.blob.core.windows.net/media/WhatsApp%20Image%202026-05-28%20at%2010.00.48%20PM.jpeg',
}

html = template.render(context)
print('HTML rendered, length:', len(html))

from xhtml2pdf import pisa
buffer = BytesIO()
pisa_status = pisa.pisaDocument(BytesIO(html.encode('utf-8')), buffer)
print('pisa_status.err:', pisa_status.err)
print('buffer size:', len(buffer.getvalue()))
