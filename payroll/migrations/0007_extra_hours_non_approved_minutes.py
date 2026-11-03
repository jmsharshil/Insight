from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('payroll', '0006_extra_hours_approval_details'),
    ]

    operations = [
        migrations.AddField(
            model_name='extrahoursapproval',
            name='non_approved_extra_minutes',
            field=models.IntegerField(default=0),
        ),
    ]
