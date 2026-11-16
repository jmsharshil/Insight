from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('payroll', '0007_extra_hours_non_approved_minutes'),
    ]

    operations = [
        migrations.AddField(
            model_name='payslip',
            name='retention_refund_amount',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
    ]
