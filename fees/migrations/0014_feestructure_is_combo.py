from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('fees', '0013_payment_admission_alter_payment_status_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='feestructure',
            name='is_combo',
            field=models.BooleanField(
                default=False,
                help_text='Use this fee structure for CSEET + CS Executive combo admissions.',
            ),
        ),
    ]
