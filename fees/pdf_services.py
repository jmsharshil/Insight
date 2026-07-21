import logging
import sys
import hashlib
from io import BytesIO
from django.template.loader import get_template
from django.conf import settings
from core.number_utils import num2words
from asgiref.sync import async_to_sync

# ── Python 3.8 compat: hashlib.md5 doesn't support usedforsecurity kwarg.
# reportlab 4.x and xhtml2pdf pass it, causing TypeError on Python 3.8.
if sys.version_info < (3, 9):
    _original_md5 = hashlib.md5

    def _md5_compat(*args, **kwargs):
        kwargs.pop('usedforsecurity', None)
        return _original_md5(*args, **kwargs)

    hashlib.md5 = _md5_compat

logger = logging.getLogger(__name__)


def _reportlab_receipt_pdf(context):
    """
    Generate a receipt PDF using reportlab (pure Python, no system libs needed).
    Serves as a reliable fallback when WeasyPrint/Playwright/xhtml2pdf all fail.
    Accepts the same `context` dict as the Django template.
    """
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

    # Header: Institute info
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

    # Title bar
    title_data = [[Paragraph('RECEIPT', title_style)]]
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

    subtitle = Paragraph('Experience - Expertise - Excellence', heading_style)
    elements.append(subtitle)
    elements.append(Spacer(1, 8 * mm))

    # Receipt No & Date row
    meta_data = [
        [
            Paragraph(f'<b>Receipt Date:</b> {context.get("receipt_date", "")}', label_style),
            Paragraph(f'<b>Receipt No:</b> <font size="13">{context.get("receipt_no", "")}</font>', label_style),
        ]
    ]
    meta_table = Table(meta_data, colWidths=[doc.width * 0.5, doc.width * 0.5])
    meta_table.setStyle(TableStyle([
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
    ]))
    elements.append(meta_table)
    elements.append(Spacer(1, 5 * mm))

    # Details rows
    details = [
        ('Received From M/s.', context.get('student_name', 'N/A')),
        ('Amount', context.get('amount', '')),
        ('Amount in Words', context.get('amount_words', '')),
        ('Batch', context.get('batch_name', 'N/A')),
    ]
    for lbl, val in details:
        row = Table(
            [[Paragraph(f'<b>{lbl}:</b>', label_style),
              Paragraph(str(val), value_style)]],
            colWidths=[doc.width * 0.3, doc.width * 0.7],
        )
        row.setStyle(TableStyle([
            ('LINEBELOW', (1, 0), (1, 0), 0.5, HexColor('#999999')),
            ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
        ]))
        elements.append(row)
        elements.append(Spacer(1, 2 * mm))

    elements.append(Spacer(1, 3 * mm))

    # Payment type checkboxes
    pt = context.get('payment_type', 'installment')
    checks = []
    for key, label in [('token', 'Token'), ('full', 'Full Payment'), ('installment', 'Installment')]:
        mark = '✓' if pt == key else '  '
        checks.append(f'[ {mark} ] {label}')
    elements.append(Paragraph('    '.join(checks), label_style))
    elements.append(Spacer(1, 3 * mm))

    # Payment mode checkboxes
    pm = (context.get('payment_mode', '') or '').lower()
    mode_checks = []
    for keys, label in [(['cash'], 'Cash'), (['cheque', 'dd'], 'Cheque'), (['online', 'upi'], 'Online')]:
        mark = '✓' if pm in keys else '  '
        mode_checks.append(f'[ {mark} ] {label}')
    elements.append(Paragraph(f'<b>By</b>    ' + '    '.join(mode_checks), label_style))
    elements.append(Spacer(1, 5 * mm))

    # Transaction details
    tx_details = [
        ('Cheque / Transaction No.', context.get('transaction_ref', 'N/A')),
        ('Cheque/Transaction Date', context.get('transaction_date', '')),
    ]
    for lbl, val in tx_details:
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

    elements.append(Spacer(1, 15 * mm))

    # Footer
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
                'FOR, Insight Institute of Professional Studies<br/><br/><br/><br/>'
                '___________________________<br/>'
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
    """Helper for Playwright fallback using async_to_sync + Chromium for accurate
    CSS/watermark rendering (used when WeasyPrint fails on fonts or complex layouts).
    """
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
        logger.error(
            "Playwright not installed. Cannot use PDF fallback. "
            "Install with: pip install playwright && playwright install chromium"
        )
        return None
    except Exception as pw_err:
        logger.error(f"Playwright fallback failed: {pw_err}", exc_info=True)
        return None

def generate_payment_receipt_pdf(payment):
    """
    Generate a professional PDF receipt. Primary: WeasyPrint (with FontConfiguration
    + Indian-rupee num2words). On exception or empty buffer, falls back to Playwright
    via dedicated helper (async_to_sync). Returns (BytesIO, method) tuple or (None, None).
    """
    try:
        template = get_template('fees/receipt.html')
        
        # Determine payment type (token vs full vs installment)
        payment_type = 'installment'
        try:
            admission = getattr(payment.student, 'admission', None)
        except Exception:
            admission = None

        try:
            student_fee_total = payment.student_fee.total_amount if payment.student_fee else None
        except Exception:
            student_fee_total = None
        
        if student_fee_total is not None:
            try:
                if (
                    admission
                    and getattr(admission, 'payment_amount', None) == payment.amount
                    and payment.amount < student_fee_total
                ):
                    payment_type = 'token'
                elif payment.amount >= student_fee_total:
                    payment_type = 'full'
            except TypeError:
                pass  # leave as 'installment' if comparison fails

        # Safe date fallback
        from django.utils import timezone as tz
        if payment.payment_date:
            receipt_date_str = payment.payment_date.strftime('%d %b, %Y')
        else:
            try:
                receipt_date_str = tz.localtime(payment.created_at).strftime('%d %b, %Y')
            except Exception:
                receipt_date_str = tz.localtime().strftime('%d %b, %Y')

        # Safe batch name
        try:
            batch_name = (
                payment.student_fee.fee_structure.batch.name
                if payment.student_fee
                and getattr(payment.student_fee, 'fee_structure', None)
                and getattr(payment.student_fee.fee_structure, 'batch', None)
                else 'N/A'
            )
        except Exception:
            batch_name = 'N/A'

        context = {
            'receipt_no': payment.receipt_number or f"REC-{payment.id}",
            'receipt_date': receipt_date_str,
            'student_name': getattr(payment.student, 'full_name', 'N/A'),
            'amount': f"\u20b9{payment.amount:,.2f}",
            'amount_words': num2words(payment.amount),
            'batch_name': batch_name,
            'payment_type': payment_type,
            'payment_mode': payment.payment_mode or 'N/A',
            'transaction_ref': payment.transaction_ref or 'N/A',
            'transaction_date': (
                payment.payment_date.strftime('%d %b, %Y') if payment.payment_date else ''
            ),
            # 'school_name': getattr(settings, 'SCHOOL_NAME', 'Your School Name'),
            # 'school_address': getattr(settings, 'SCHOOL_ADDRESS', ''),
            'logo_url': 'https://insightsinstitutes.blob.core.windows.net/media/insight.png',
        }
        
        html = template.render(context)
        
        # Primary: WeasyPrint (fast, no browser required)
        try:
            from weasyprint import HTML
            from weasyprint.text.fonts import FontConfiguration
            font_config = FontConfiguration()
            html_doc = HTML(string=html, base_url=str(settings.BASE_DIR))
            buffer = BytesIO()
            html_doc.write_pdf(buffer, font_config=font_config)
            buffer.seek(0)
            if buffer.getvalue():  # ensure non-empty
                logger.info(f"Successfully generated PDF receipt using WeasyPrint for payment {payment.id}")
                return buffer, 'weasyprint'
            raise ValueError("WeasyPrint produced empty buffer")
        except Exception as weasy_err:
            logger.warning(
                f"WeasyPrint failed for payment {getattr(payment, 'id', 'N/A')}: {weasy_err}. "
                "Falling back to Playwright."
            )
        
        # Fallback 1: Playwright
        buffer = playwright_pdf(html)
        if buffer and buffer.getvalue():
            logger.info(f"Successfully generated PDF receipt using Playwright fallback for payment {payment.id}")
            return buffer, 'playwright'
            
        logger.warning(f"Both WeasyPrint and Playwright failed for payment {getattr(payment, 'id', 'N/A')}. Falling back to xhtml2pdf.")
        
        # Fallback 2: xhtml2pdf (Pure Python, highest reliability on unconfigured servers)
        try:
            from xhtml2pdf import pisa
            buffer = BytesIO()
            # xhtml2pdf expects bytes input
            pisa_status = pisa.pisaDocument(BytesIO(html.encode('utf-8')), buffer)
            if not pisa_status.err and buffer.getvalue():
                buffer.seek(0)
                logger.info(f"Successfully generated PDF receipt using xhtml2pdf fallback for payment {payment.id}")
                return buffer, 'xhtml2pdf'
        except Exception as xhtml_err:
            logger.error(f"xhtml2pdf fallback failed: {xhtml_err}")

        # Fallback 3: reportlab (pure Python, no system libs needed — works everywhere)
        try:
            buffer = _reportlab_receipt_pdf(context)
            if buffer and buffer.getvalue():
                logger.info(f"Successfully generated PDF receipt using reportlab fallback for payment {payment.id}")
                return buffer, 'reportlab'
        except Exception as rl_err:
            logger.error(f"reportlab fallback failed: {rl_err}")

        logger.error(f"ALL PDF generation methods (WeasyPrint, Playwright, xhtml2pdf, reportlab) failed for payment {getattr(payment, 'id', 'N/A')}")
        return None, None
            
    except Exception as e:
        logger.error(f"Failed to generate PDF for payment {getattr(payment, 'id', 'N/A')}: {str(e)}", exc_info=True)
        return None, None

