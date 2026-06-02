"""
reports/exporters.py — CSV and PDF export helpers.
"""
import csv
import io
from datetime import datetime
from django.http import StreamingHttpResponse, HttpResponse


# ═══════════════════════════════════════════════════════════════════════════════
#  CSV Export (streaming, memory-efficient)
# ═══════════════════════════════════════════════════════════════════════════════

class Echo:
    """Pseudo-buffer for StreamingHttpResponse CSV writer."""
    def write(self, value):
        return value


def export_csv(headers, rows, filename='report.csv'):
    """
    Stream a CSV response. Memory-efficient for large datasets.

    Args:
        headers: list of column header strings
        rows: iterable of lists/tuples matching headers
        filename: download filename
    """
    pseudo_buffer = Echo()
    writer = csv.writer(pseudo_buffer)

    def generate():
        yield writer.writerow(headers)
        for row in rows:
            yield writer.writerow(row)

    response = StreamingHttpResponse(generate(), content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


# ═══════════════════════════════════════════════════════════════════════════════
#  PDF Export (reportlab)
# ═══════════════════════════════════════════════════════════════════════════════

def export_pdf(title, headers, rows, filename='report.pdf', landscape=False):
    """
    Generate a professional tabular PDF report.

    Falls back to CSV if reportlab is not installed.
    """
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape as rl_landscape
        from reportlab.lib.units import inch
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet
    except ImportError:
        # Fallback to CSV if reportlab not installed
        return export_csv(headers, rows, filename.replace('.pdf', '.csv'))

    buffer = io.BytesIO()
    page_size = rl_landscape(A4) if landscape else A4

    doc = SimpleDocTemplate(buffer, pagesize=page_size,
                            leftMargin=0.5 * inch, rightMargin=0.5 * inch,
                            topMargin=0.5 * inch, bottomMargin=0.5 * inch)

    styles = getSampleStyleSheet()
    elements = []

    # Title
    elements.append(Paragraph(title, styles['Title']))
    elements.append(Spacer(1, 6))
    elements.append(Paragraph(
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        styles['Normal']
    ))
    elements.append(Spacer(1, 12))

    # Table data
    table_data = [headers]
    for row in rows:
        table_data.append([str(cell) if cell is not None else '' for cell in row])

    if len(table_data) > 1:
        col_count = len(headers)
        available_width = page_size[0] - 1 * inch
        col_width = available_width / col_count if col_count else available_width

        table = Table(table_data, colWidths=[col_width] * col_count)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2C3E50')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#ECF0F1')]),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        elements.append(table)
    else:
        elements.append(Paragraph("No data available.", styles['Normal']))

    doc.build(elements)
    buffer.seek(0)

    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
