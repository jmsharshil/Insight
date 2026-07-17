import logging
from io import BytesIO
from django.template.loader import get_template
from django.conf import settings
from weasyprint import HTML
from weasyprint.text.fonts import FontConfiguration
from core.number_utils import num2words
from asgiref.sync import async_to_sync

logger = logging.getLogger(__name__)


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
            
        if (
            admission
            and getattr(admission, 'payment_amount', 0) == payment.amount
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
        
        # Primary: WeasyPrint (fast, no browser required)
        try:
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
        
        # Fallback
        buffer = playwright_pdf(html)
        if buffer and buffer.getvalue():
            logger.info(f"Successfully generated PDF receipt using Playwright fallback for payment {payment.id}")
            return buffer, 'playwright'
        logger.error(f"Both WeasyPrint and Playwright failed for payment {getattr(payment, 'id', 'N/A')}")
        return None, None
            
    except Exception as e:
        logger.error(f"Failed to generate PDF for payment {getattr(payment, 'id', 'N/A')}: {str(e)}", exc_info=True)
        return None, None

