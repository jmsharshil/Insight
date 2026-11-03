from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('exams', '0013_supervisor_duty_log'),
    ]

    operations = [
        migrations.AddField(
            model_name='supervisordutylog',
            name='payable_hours',
            field=models.DecimalField(decimal_places=1, default=0, max_digits=3),
        ),
    ]
