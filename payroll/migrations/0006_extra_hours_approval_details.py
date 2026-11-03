from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('payroll', '0005_add_is_manually_adjusted_to_payslip'),
    ]

    operations = [
        migrations.AddField(
            model_name='extrahoursapproval',
            name='approval_reason',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='extrahoursapproval',
            name='approved_extra_minutes',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='extrahoursapproval',
            name='daily_details',
            field=models.JSONField(blank=True, default=list),
        ),
    ]
