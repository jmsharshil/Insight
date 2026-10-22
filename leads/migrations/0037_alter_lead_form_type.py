from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('leads', '0036_salesdailyactivity_self_vehicle_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='lead',
            name='form_type',
            field=models.CharField(
                choices=[
                    ('contact', 'Contact Us'),
                    ('inquiry', 'Inquiry Form'),
                    ('admission', 'Admission Form'),
                ],
                max_length=20,
            ),
        ),
    ]
