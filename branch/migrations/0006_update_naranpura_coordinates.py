"""
Data migration to update Old Naranpura branch coordinates.
"""
from django.db import migrations


def update_naranpura_coords(apps, schema_editor):
    Branch = apps.get_model('branch', 'Branch')
    Branch.objects.filter(name__icontains='naranpura').update(
        latitude=23.05300132484904,
        longitude=72.55916192049834,
    )


def reverse_coords(apps, schema_editor):
    # Restore previous coordinates
    Branch = apps.get_model('branch', 'Branch')
    Branch.objects.filter(name__icontains='naranpura').update(
        latitude=23.05384207185591,
        longitude=72.5594770518486,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('branch', '0005_update_jms_test_coordinates'),
    ]

    operations = [
        migrations.RunPython(update_naranpura_coords, reverse_coords),
    ]
