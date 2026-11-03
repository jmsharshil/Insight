from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('exams', '0010_alter_subjectpaper_set_name'),
    ]

    operations = [
        migrations.CreateModel(
            name='SupervisorDutyLog',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('start_photo', models.ImageField(blank=True, null=True, upload_to='exam_supervisor/start/%Y/%m/')),
                ('end_photo', models.ImageField(blank=True, null=True, upload_to='exam_supervisor/end/%Y/%m/')),
                ('start_submitted_at', models.DateTimeField(blank=True, null=True)),
                ('end_submitted_at', models.DateTimeField(blank=True, null=True)),
                ('late_minutes', models.PositiveIntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('exam', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='supervisor_duty_logs', to='exams.exam')),
                ('supervisor', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='exam_supervisor_duty_logs', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'exam_supervisor_duty_logs',
                'unique_together': {('exam', 'supervisor')},
            },
        ),
    ]
