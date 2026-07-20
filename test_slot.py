import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'insight.settings')
django.setup()

from django.utils import timezone
from datetime import timedelta
local = timezone.localtime()
buffered_time = (local + timedelta(minutes=15)).time()
current_time = local.time()
print('Local:', local)
print('Current:', current_time)
print('Buffered:', buffered_time)
