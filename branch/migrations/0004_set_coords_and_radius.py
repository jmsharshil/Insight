"""
Data migration to:
1. Update all existing branches' allowed_radius_meters from 100 to 20
2. Set coordinates for Naranpura and JMS TEST branches
"""
from django.db import migrations


def set_branch_coords_and_radius(apps, schema_editor):
    Branch = apps.get_model('branch', 'Branch')

    # Update all existing branches that still have the old default (100m) to 20m
    Branch.objects.filter(allowed_radius_meters=100).update(allowed_radius_meters=20)

    # Set Naranpura branch coordinates
    Branch.objects.filter(name__icontains='naranpura').update(
        latitude=23.05384207185591,
        longitude=72.5594770518486,
    )

    # Set JMS TEST branch coordinates
    Branch.objects.filter(name__icontains='jms test').update(
        latitude=23.02014263437688,
        longitude=72.55650043611708,
    )


def reverse_coords(apps, schema_editor):
    # No-op reverse — we don't want to lose coordinates
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('branch', '0003_update_radius_default'),
    ]

    operations = [
        migrations.RunPython(set_branch_coords_and_radius, reverse_coords),
    ]
