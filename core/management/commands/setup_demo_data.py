from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

# Models
from branch.models import Branch
from auth_user.models import Organization
from faculty.models import FacultyProfile

class Command(BaseCommand):
    help = 'Creates demo data for local testing'

    def handle(self, *args, **kwargs):
        self.stdout.write("Starting Demo Data setup...")

        User = get_user_model()

        # 1. Organization & Branch
        org, _ = Organization.objects.get_or_create(
            name="Demo Org"
        )
        branch, _ = Branch.objects.get_or_create(
            name="Main Branch", defaults={"organization": org, "city": "Mumbai"}
        )

        # 2. Superuser / Admin
        if not User.objects.filter(email="admin@example.com").exists():
            admin = User.objects.create_superuser(
                email="admin@example.com",
                password="password123",
                name="Admin User",
                username="admin",
                phone="9999999999"
            )
            self.stdout.write(self.style.SUCCESS("Created superuser admin@example.com / password123"))
        else:
            self.stdout.write(self.style.WARNING("Superuser admin@example.com already exists."))

        # 3. Faculty
        faculty_user, created = User.objects.get_or_create(
            email="faculty@example.com",
            defaults={"name": "Demo Faculty", "phone": "8888888888", "role": "faculty", "username": "faculty","joining_date": "2022-01-01"}
        )
        if created:
            faculty_user.set_password("password123")
            faculty_user.save()

        faculty_profile, _ = FacultyProfile.objects.get_or_create(
            user=faculty_user, defaults={"branch": branch, "employee_id": "FAC001","joining_date": "2022-01-01"}
        )
        self.stdout.write(self.style.SUCCESS("Created faculty faculty@example.com / password123"))

        self.stdout.write(self.style.SUCCESS("Demo Data setup complete!"))
