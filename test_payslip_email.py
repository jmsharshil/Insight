import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'insight.settings')
django.setup()

from payroll.models import PaySlip
from payroll.pdf_services import generate_payslip_pdf
from core.sender import send_email

def test_payslip_email_direct():
    payslip = PaySlip.objects.last()
    if not payslip:
        print("No payslip to test.")
        return
        
    recipient_user = payslip.faculty.user if payslip.faculty else payslip.user
    if not recipient_user or not getattr(recipient_user, 'email', None):
        print("No email on user")
        return
        
    print(f"Generating PDF for {recipient_user.email}...")
    buffer, method = generate_payslip_pdf(payslip)
    
    if not buffer:
        print("Failed to generate PDF")
        return
        
    attachments = []
    filename = f"Payslip_{payslip.payroll_run.month}_{payslip.payroll_run.year}.pdf"
    attachments.append((filename, buffer.getvalue(), 'application/pdf'))
    print(f"Generated PDF ({len(buffer.getvalue())} bytes) using {method}")
    
    ctx = {
        'user_name': recipient_user.name,
        'month': payslip.payroll_run.month,
        'year': payslip.payroll_run.year,
        'net_salary': payslip.net_salary,
        'sessions': payslip.sessions_conducted
    }
    
    print("Calling send_email...")
    result = send_email(
        to=recipient_user.email,
        subject=f"Your payslip for {payslip.payroll_run.month}/{payslip.payroll_run.year} is ready",
        text=f"Net salary: {payslip.net_salary}. Sessions: {payslip.sessions_conducted}.",
        template='emails/payslip_generated.html',
        template_context=ctx,
        organization=getattr(recipient_user, 'organization', None),
        attachments=attachments
    )
    
    print(f"Send email result: {result}")

if __name__ == "__main__":
    test_payslip_email_direct()
