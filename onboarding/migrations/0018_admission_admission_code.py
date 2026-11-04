from django.db import migrations, models


def populate_admission_codes(apps, schema_editor):
    Admission = apps.get_model('onboarding', 'Admission')
    for admission in Admission.objects.filter(admission_code='').iterator():
        Admission.objects.filter(pk=admission.pk).update(
            admission_code=f"IIPS-{admission.pk:06d}"
        )


def clear_admission_codes(apps, schema_editor):
    Admission = apps.get_model('onboarding', 'Admission')
    Admission.objects.update(admission_code='')


class Migration(migrations.Migration):

    dependencies = [
        ('onboarding', '0017_admission_combo_future_attempt_year_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='admission',
            name='admission_code',
            field=models.CharField(
                blank=True,
                db_index=True,
                editable=False,
                help_text='Human-readable admission code (for example, IIPS-000001).',
                max_length=30,
                unique=False,
            ),
        ),
        migrations.RunPython(populate_admission_codes, clear_admission_codes),
        migrations.AlterField(
            model_name='admission',
            name='admission_code',
            field=models.CharField(
                blank=True,
                db_index=True,
                editable=False,
                help_text='Human-readable admission code (for example, IIPS-000001).',
                max_length=30,
                unique=True,
            ),
        ),
    ]
