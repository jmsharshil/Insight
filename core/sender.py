from django.core.mail import send_mail,EmailMultiAlternatives

def send_email(to,subject,cc=[],text="",template=None,attachments=None):
    msg = EmailMultiAlternatives(subject, text, "talent@knowcraft.in",to= [to],cc= cc)
    if template:
        msg.attach_alternative(template, "text/html")
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
                print("Error Attachning Documents:",e)
        pass
    msg.send()