import os, django
os.environ['DJANGO_SETTINGS_MODULE'] = 'insight.settings'
django.setup()

from batches.models import TimetableSlot
from django.db.models import Count

# Check total slots
total = TimetableSlot.objects.count()
print(f"Total TimetableSlots in DB: {total}")

# Check DOW distribution
dow_counts = list(TimetableSlot.objects.values_list('day_of_week', flat=True).distinct())
print(f"Distinct day_of_week values: {dow_counts}")

# Get a few sample slots
samples = TimetableSlot.objects.all()[:5]
for s in samples:
    print(f"  DOW={s.day_of_week} | {s.start_time}-{s.end_time} | batch={s.batch_id}")

# Check if this is the production DB or a test DB
from django.conf import settings
print(f"\nDB engine: {settings.DATABASES['default']['ENGINE']}")
print(f"DB name: {settings.DATABASES['default']['NAME']}")
