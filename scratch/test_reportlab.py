import os
import sys
from pathlib import Path
from decimal import Decimal
import uuid
from unittest.mock import MagicMock

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

# Test template rendering
from django.template.loader import get_template
t = get_template('fees/receipt.html')
print('Template loaded successfully!')

from fees.pdf_services import generate_payment_receipt_pdf

payment = MagicMock()
payment.id = uuid.uuid4()
payment.receipt_number = 'REC-TEST-001'
payment.amount = Decimal('12500.00')
payment.payment_mode = 'cash'
payment.transaction_ref = 'CASH-ADM-123'
payment.payment_date = None
payment.created_at = None
payment.student = MagicMock()
payment.student.full_name = 'Test Student'
payment.student.admission = None
payment.student_fee = None
payment.admission = None

try:
    print('Testing generate_payment_receipt_pdf...')
    result = generate_payment_receipt_pdf(payment)
    if result:
        buf, method = result
        print(f'Result: method={method}, buf_len={len(buf.getvalue()) if buf else 0}')
    else:
        print('Result is None!')
except Exception as e:
    import traceback
    traceback.print_exc()
