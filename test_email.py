import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "insight.settings")
django.setup()

from core.sender import send_email
from django.conf import settings

print("Testing send_email to:", settings.EMAIL_HOST_USER)
res = send_email(settings.EMAIL_HOST_USER, "Test email", text="This is a test")
print("send_email returned:", res)
