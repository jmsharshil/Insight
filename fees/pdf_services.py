import os
from io import BytesIO
from django.template.loader import get_template
from django.conf import settings
from weasyprint import HTML
from weasyprint.text.fonts import FontConfiguration
from core.number_utils import num2words
import logging

logger = logging.getLogger(__name__)

def generate_payment_receipt_pdf(payment):
    """
    Generate a professional PDF receipt using WeasyPrint 61.2 (stable version).
    Uses pydyf 0.11.0 to avoid 'super().transform' AttributeError.
    Returns a BytesIO buffer containing the PDF data or None on failure.
    """
    try:
        template = get_template('fees/receipt.html')
        
        # Determine payment type (token vs full vs installment)
        payment_type = 'installment'
        if (
            getattr(payment.student, 'admission', None)
            and getattr(payment.student.admission, 'payment_amount', 0) == payment.amount
            and payment.amount < getattr(payment.student_fee, 'total_amount', 0)
        ):
            payment_type = 'token'
        elif payment.amount >= getattr(payment.student_fee, 'total_amount', 0):
            payment_type = 'full'
            
        context = {
            'receipt_no': payment.receipt_number or f"REC-{payment.id}",
            'receipt_date': (
                payment.payment_date.strftime('%d %b, %Y')
                if payment.payment_date
                else payment.created_at.strftime('%d %b, %Y')
            ),
            'student_name': getattr(payment.student, 'full_name', 'N/A'),
            'amount': f"₹{payment.amount:,.2f}",
            'amount_words': num2words(payment.amount),
            'batch_name': (
                payment.student_fee.fee_structure.batch.name
                if getattr(payment.student_fee, 'fee_structure', None)
                and getattr(payment.student_fee.fee_structure, 'batch', None)
                else 'N/A'
            ),
            'payment_type': payment_type,
            'payment_mode': payment.payment_mode or 'N/A',
            'transaction_ref': payment.transaction_ref or 'N/A',
            'transaction_date': (
                payment.payment_date.strftime('%d %b, %Y') if payment.payment_date else ''
            ),
            'school_name': getattr(settings, 'SCHOOL_NAME', 'Your School Name'),
            'school_address': getattr(settings, 'SCHOOL_ADDRESS', ''),
            'logo_url': 'https://insightsinstitutes.blob.core.windows.net/media/insight.png',
        }
        
        html = template.render(context)
        result = BytesIO()
        
        # Professional PDF generation with WeasyPrint
        font_config = FontConfiguration()
        html_doc = HTML(string=html, base_url=str(settings.BASE_DIR))
        html_doc.write_pdf(result, font_config=font_config)
        
        result.seek(0)
        logger.info(f"Successfully generated professional PDF receipt for payment {payment.id}")
        return result
        
    except Exception as e:
        logger.error(f"Failed to generate PDF for payment {getattr(payment, 'id', 'N/A')}: {str(e)}", exc_info=True)
        return None

