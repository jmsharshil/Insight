# Generated migration for session_name field on TimetableSlot

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('batches', '0016_timetableslot_exam'),
    ]

    operations = [
        migrations.AddField(
            model_name='timetableslot',
            name='session_name',
            field=models.CharField(blank=True, max_length=200),
        ),
    ]
