import os
from io import BytesIO
from django.template.loader import get_template
from django.conf import settings
from xhtml2pdf import pisa
from core.number_utils import num2words

def generate_payment_receipt_pdf(payment):
    """
    Generate a PDF receipt for a given payment.
    Returns a BytesIO buffer containing the PDF data.
    """
    template = get_template('fees/receipt.html')
    
    # Determine payment type (token vs full vs installment)
    # This is a bit of a guess based on amount and total due, but we try to be smart.
    payment_type = 'installment'
    if getattr(payment.student, 'admission', None) and getattr(payment.student.admission, 'payment_amount', 0) == payment.amount and payment.amount < payment.student_fee.total_amount:
        payment_type = 'token'
    elif payment.amount >= payment.student_fee.total_amount:
        payment_type = 'full'
        
    context = {
        'receipt_no': payment.receipt_number or f"{payment.id}",
        'receipt_date': payment.payment_date.strftime('%d-%m-%Y') if payment.payment_date else payment.created_at.strftime('%d-%m-%Y'),
        'student_name': payment.student.full_name,
        'amount': f"{payment.amount:,.2f}",
        'amount_words': num2words(payment.amount),
        'batch_name': payment.student_fee.fee_structure.batch.name if getattr(payment.student_fee.fee_structure, 'batch', None) else 'N/A',
        'payment_type': payment_type,
        'payment_mode': payment.payment_mode,
        'transaction_ref': payment.transaction_ref or 'N/A',
        'transaction_date': payment.payment_date.strftime('%d-%m-%Y') if payment.payment_date else '',
    }
    
    html = template.render(context)
    result = BytesIO()
    
    # Generate PDF
    pdf = pisa.pisaDocument(BytesIO(html.encode("UTF-8")), result)
    
    if not pdf.err:
        return result
    return None
