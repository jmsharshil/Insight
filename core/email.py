from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings

def send_email(
    to,
    subject,
    cc=None,
    text="",
    template=None,
    template_context=None,
    organization=None,
    attachments=None,
    use_default_cc=False,
):
    """
    Central utility to send emails.
    Supports plain text and HTML template rendering with organization branding.
    """
    cc_list = list(cc) if cc else []
    if use_default_cc:
        cc_list.append("talent@knowcraft.in")

    from_email = settings.DEFAULT_FROM_EMAIL

    html_body = None
    if template:
        ctx = {**(template_context or {})}
        if organization:
            ctx.update({
                'org_name': organization.name,
                'logo_url': organization.logo_url,
                'footer_text': organization.footer_text,
                'primary_color': organization.primary_color,
                'website_url': organization.website_url,
            })
        else:
            ctx.setdefault('org_name', 'Insight ERP')
            ctx.setdefault('logo_url', '')
            ctx.setdefault('footer_text', '')
            ctx.setdefault('primary_color', '#2563EB')
            ctx.setdefault('website_url', '')

        html_body = render_to_string(template, ctx)

    msg = EmailMultiAlternatives(subject, text, from_email, to=[to], cc=cc_list)
    
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
                    # attachment is a tuple (filename, content_bytes, mimetype)
                    msg.attach(*attachment)
            except Exception as e:
                print("Error Attaching Documents:", e)
                
    msg.send()
