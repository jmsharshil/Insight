from django.core.mail import send_mail, EmailMultiAlternatives
from django.template.loader import render_to_string

def send_email(to, subject, cc=[], text="", template=None, attachments=None, template_context=None, organization=None):
    msg = EmailMultiAlternatives(subject, text, "talent@knowcraft.in", to=[to], cc=cc)
    
    html_body = template
    if template and template.endswith(".html"):
        ctx = {**(template_context or {})}
        if organization:
            ctx.update({
                'org_name': getattr(organization, 'name', ''),
                'logo_url': getattr(organization, 'logo_url', ''),
                'footer_text': getattr(organization, 'footer_text', ''),
                'primary_color': getattr(organization, 'primary_color', ''),
                'website_url': getattr(organization, 'website_url', ''),
            })
        else:
            ctx.setdefault('org_name', 'Insight ERP')
            ctx.setdefault('logo_url', '')
            ctx.setdefault('footer_text', '')
            ctx.setdefault('primary_color', '#2563EB')
            ctx.setdefault('website_url', '')
            
        html_body = render_to_string(template, ctx)

    if html_body:
        msg.attach_alternative(html_body, "text/html")
        
    if attachments:
        for attachment in attachments:
            try:
                if isinstance(attachment, str):
                    # attachment is a file path
                    filename = attachment.split("/")[-1]
                    with open(attachment, "rb") as f:
                        msg.attach(filename, f.read(), "application/pdf")
                else:
                    # attachment is a tuple
                    # (filename, content_bytes, mimetype)
                    msg.attach(*attachment)
            except Exception as e:
                print("Error Attachning Documents:", e)

    msg.send()