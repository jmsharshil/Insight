import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('fees', '0014_feestructure_is_combo'),
        ('onboarding', '0018_admission_admission_code'),
    ]

    operations = [
        migrations.AddField(
            model_name='admission',
            name='combo_fee_structure',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='combo_admissions',
                to='fees.feestructure',
            ),
        ),
    ]
