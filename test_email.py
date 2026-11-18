import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "insight.settings")
django.setup()

from core.sender import send_email
from django.conf import settings

print("Testing send_email to: anand@jmstech.co")
res = send_email("anand@jmstech.co", "Test email", text="This is a test")
print("send_email returned:", res)
