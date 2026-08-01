import logging
import sys
import hashlib
from io import BytesIO
from django.template.loader import get_template
from django.conf import settings
from core.number_utils import num2words
from asgiref.sync import async_to_sync

if sys.version_info < (3, 9):
    _original_md5 = hashlib.md5
    def _md5_compat(*args, **kwargs):
        kwargs.pop('usedforsecurity', None)
        return _original_md5(*args, **kwargs)
    hashlib.md5 = _md5_compat

logger = logging.getLogger(__name__)


def _reportlab_payslip_pdf(context):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm, mm
    from reportlab.lib.colors import HexColor, black, white
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=1.5 * cm, rightMargin=1.5 * cm,
        topMargin=1.5 * cm, bottomMargin=1.5 * cm,
    )

    orange = HexColor('#ed7c31')
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle('ReceiptTitle', parent=styles['Title'],
                                  fontSize=22, textColor=white, alignment=TA_CENTER)
    heading_style = ParagraphStyle('ReceiptHeading', parent=styles['Heading2'],
                                    fontSize=14, textColor=orange, alignment=TA_CENTER)
    label_style = ParagraphStyle('Label', parent=styles['Normal'],
                                  fontSize=11, textColor=black, leading=16)
    value_style = ParagraphStyle('Value', parent=styles['Normal'],
                                  fontSize=11, textColor=HexColor('#333333'), leading=16)
    small_style = ParagraphStyle('Small', parent=styles['Normal'],
                                  fontSize=9, textColor=HexColor('#666666'), leading=12)

    elements = []

    header_data = [
        [
            Paragraph('<b>77780 50578 | 99745 45456</b><br/>'
                      'www.insightinstitute.com<br/>'
                      'insightinstitute.ips@gmail.com', small_style),
            Paragraph('<b>INSIGHT</b><br/>Institute of Professional Studies',
                      ParagraphStyle('Logo', parent=heading_style, fontSize=14, alignment=TA_RIGHT)),
        ]
    ]
    header_table = Table(header_data, colWidths=[doc.width * 0.5, doc.width * 0.5])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LINEBELOW', (0, 0), (-1, 0), 2, orange),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 8 * mm))

    title_data = [[Paragraph('PAYSLIP', title_style)]]
    title_table = Table(title_data, colWidths=[doc.width])
    title_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), orange),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('ROUNDEDCORNERS', [4, 4, 4, 4]),
    ]))
    elements.append(title_table)
    elements.append(Spacer(1, 5 * mm))

    subtitle = Paragraph(context.get('month_year', ''), heading_style)
    elements.append(subtitle)
    elements.append(Spacer(1, 8 * mm))

    details = [
        ('Employee Name', context.get('employee_name', '')),
        ('Employee ID', context.get('employee_id', '')),
        ('Role', context.get('role', '')),
        ('Branch', context.get('branch_name', '')),
    ]
    for lbl, val in details:
        row = Table(
            [[Paragraph(f'<b>{lbl}:</b>', label_style),
              Paragraph(str(val), value_style)]],
            colWidths=[doc.width * 0.35, doc.width * 0.65],
        )
        row.setStyle(TableStyle([
            ('LINEBELOW', (1, 0), (1, 0), 0.5, HexColor('#999999')),
            ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
        ]))
        elements.append(row)
        elements.append(Spacer(1, 2 * mm))

    elements.append(Spacer(1, 10 * mm))

    # Basic table for earnings/deductions
    t_data = [
        [Paragraph('<b>Earnings</b>', label_style), Paragraph('<b>Amount (Rs.)</b>', ParagraphStyle('R', parent=label_style, alignment=TA_RIGHT))],
        [Paragraph('Gross Salary', label_style), Paragraph(str(context.get('gross_salary', 0)), ParagraphStyle('R', parent=value_style, alignment=TA_RIGHT))],
        [Paragraph('<b>Deductions</b>', label_style), Paragraph('<b>Amount (Rs.)</b>', ParagraphStyle('R', parent=label_style, alignment=TA_RIGHT))],
        [Paragraph('Total Deductions', label_style), Paragraph(str(context.get('total_deductions', 0)), ParagraphStyle('R', parent=value_style, alignment=TA_RIGHT))],
    ]
    t_table = Table(t_data, colWidths=[doc.width * 0.6, doc.width * 0.4])
    t_table.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 1, HexColor('#cccccc')),
        ('BACKGROUND', (0,0), (-1,0), HexColor('#f9f9f9')),
        ('BACKGROUND', (0,2), (-1,2), HexColor('#f9f9f9')),
    ]))
    elements.append(t_table)
    elements.append(Spacer(1, 10 * mm))

    elements.append(Paragraph(f'<font color="#ed7c31"><b>Net Salary Payable:</b></font> <b>{context.get("net_salary", "")}</b>', ParagraphStyle('Net', parent=label_style, fontSize=14)))
    elements.append(Spacer(1, 2 * mm))
    elements.append(Paragraph(f'<b>Amount in words:</b> {context.get("amount_words", "")}', label_style))
    
    if context.get('deduction_note'):
        elements.append(Spacer(1, 5 * mm))
        elements.append(Paragraph(f'<b>Note:</b> {context.get("deduction_note", "")}', small_style))

    elements.append(Spacer(1, 15 * mm))

    footer_data = [
        [
            Paragraph(
                '<b>Vastral Branch:</b><br/>'
                '(Parth Classes) 212, Siddhi Vinayak Complex,<br/>'
                'Nr. Nirant Chokdi, Vastral Road, A\'bad - 382413<br/><br/>'
                '<b>INSIGHT INSTITUTE:</b><br/>'
                'INSIGHT HOUSE, 1st Floor, Bunglow No-2,<br/>'
                'Shreeji Society, Behind Gautam Nagar Bus Stand,<br/>'
                'Naranpura, Ahmedabad - 380013', small_style),
            Paragraph(
                'FOR, Insight Institute of Professional Studies<br/><br/><br/>'
                '<i>(Digitally Signed)</i><br/><br/>'
                '<b>Authorised Signatory</b>',
                ParagraphStyle('Footer', parent=small_style, alignment=TA_RIGHT)),
        ]
    ]
    footer_table = Table(footer_data, colWidths=[doc.width * 0.55, doc.width * 0.45])
    footer_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    elements.append(footer_table)

    doc.build(elements)
    buffer.seek(0)
    return buffer


def playwright_pdf(html: str) -> BytesIO:
    try:
        from playwright.async_api import async_playwright
        async def _render():
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.set_content(html, wait_until="networkidle")
                pdf_bytes = await page.pdf(
                    format="A4",
                    print_background=True,
                    margin={"top": "1cm", "right": "1cm", "bottom": "1cm", "left": "1cm"},
                )
                await browser.close()
                return pdf_bytes
        pdf_bytes = async_to_sync(_render)()
        buffer = BytesIO(pdf_bytes)
        buffer.seek(0)
        return buffer
    except ImportError:
        logger.error("Playwright not installed.")
        return None
    except Exception as pw_err:
        logger.error(f"Playwright fallback failed: {pw_err}")
        return None


def generate_payslip_pdf(payslip):
    try:
        template = get_template('payroll/payslip_pdf.html')
        
        pr = payslip.payroll_run
        import calendar
        month_name = calendar.month_name[pr.month]
        
        employee_name = payslip.faculty.user.name if payslip.faculty else (payslip.user.name if payslip.user else 'Unknown')
        employee_id = payslip.faculty.employee_id if payslip.faculty else (payslip.user.employee_id if getattr(payslip.user, 'employee_id', None) else 'N/A')
        role = payslip.faculty.employment_type if payslip.faculty else (payslip.user.role if payslip.user else 'N/A')
        
        gross_salary = payslip.basic_salary + payslip.hour_based_amount + payslip.bonus + payslip.attendance_bonus + payslip.leave_encashment
        total_deductions = payslip.late_penalty + payslip.absence_deductions + payslip.leave_deductions + payslip.retention_deduction + payslip.other_deductions
        
        raw_sig_url = 'https://insightsinstitutes.blob.core.windows.net/media/WhatsApp%20Image%202026-05-28%20at%2010.00.48%20PM.jpeg'
        processed_sig_url = raw_sig_url
        try:
            import requests
            import base64
            from PIL import Image
            resp = requests.get(raw_sig_url, timeout=5)
            if resp.status_code == 200:
                img = Image.open(BytesIO(resp.content)).convert("RGBA")
                datas = img.getdata()
                new_data = []
                for item in datas:
                    lum = (item[0]*299 + item[1]*587 + item[2]*114) / 1000
                    if lum > 160:
                        new_data.append((255, 255, 255, 0))
                    else:
                        new_data.append((item[0], item[1], item[2], 255))
                img.putdata(new_data)
                bbox = img.getbbox()
                if bbox:
                    img = img.crop(bbox)
                buf = BytesIO()
                img.save(buf, format="PNG")
                b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
                processed_sig_url = f"data:image/png;base64,{b64}"
        except Exception as e:
            pass

        context = {
            'month_year': f"{month_name} {pr.year}",
            'employee_name': employee_name,
            'employee_id': employee_id,
            'role': role.replace('_', ' ').title(),
            'branch_name': pr.branch.name if pr.branch else 'N/A',
            
            'basic_salary': payslip.basic_salary,
            'hour_based_amount': payslip.hour_based_amount,
            'attendance_bonus': payslip.attendance_bonus,
            'leave_encashment': payslip.leave_encashment,
            'bonus': payslip.bonus,
            'gross_salary': gross_salary,
            
            'late_penalty': payslip.late_penalty,
            'late_penalty_minutes': payslip.late_penalty_minutes,
            'absence_deductions': payslip.absence_deductions,
            'leave_deductions': payslip.leave_deductions,
            'leaves_taken': payslip.leaves_taken,
            'retention_deduction': payslip.retention_deduction,
            'other_deductions': payslip.other_deductions,
            'total_deductions': total_deductions,
            
            'net_salary': f"\u20b9{payslip.net_salary:,.2f}",
            'amount_words': num2words(payslip.net_salary),
            'deduction_note': payslip.deduction_note,
            
            'logo_url': 'https://insightsinstitutes.blob.core.windows.net/media/insight.png',
            'signature_url': processed_sig_url,
        }
        
        html = template.render(context)
        
        try:
            from weasyprint import HTML
            from weasyprint.text.fonts import FontConfiguration
            font_config = FontConfiguration()
            html_doc = HTML(string=html, base_url=str(settings.BASE_DIR))
            buffer = BytesIO()
            html_doc.write_pdf(buffer, font_config=font_config)
            buffer.seek(0)
            if buffer.getvalue():
                return buffer, 'weasyprint'
        except Exception as weasy_err:
            pass
        
        buffer = playwright_pdf(html)
        if buffer and buffer.getvalue():
            return buffer, 'playwright'
            
        try:
            from xhtml2pdf import pisa
            buffer = BytesIO()
            pisa_status = pisa.pisaDocument(BytesIO(html.encode('utf-8')), buffer)
            if not pisa_status.err and buffer.getvalue():
                buffer.seek(0)
                return buffer, 'xhtml2pdf'
        except Exception:
            pass

        try:
            buffer = _reportlab_payslip_pdf(context)
            if buffer and buffer.getvalue():
                return buffer, 'reportlab'
        except Exception:
            pass

        return None, None
            
    except Exception as e:
        logger.error(f"Failed to generate PDF for payslip {getattr(payslip, 'id', 'N/A')}: {str(e)}", exc_info=True)
        return None, None
