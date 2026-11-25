"""
schofee_finance/management/commands/sync_schofee_courses.py
────────────────────────────────────────────────────────────
Management command to fetch courses from SchoFee B2B API and synchronize
them into the local CourseMapping model.
"""

from decimal import Decimal
from django.core.management.base import BaseCommand
from schofee_finance.models import CourseMapping
from schofee_finance.services.client import SchoFeeClient
from schofee_finance.services.exceptions import SchoFeeAPIError


class Command(BaseCommand):
    help = "Synchronizes course catalog from SchoFee B2B API into CourseMapping."

    def add_arguments(self, parser):
        parser.add_argument(
            "--page-size",
            type=int,
            default=100,
            help="Number of courses to fetch per request (max 100).",
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("=== Synchronizing SchoFee Course Catalog ==="))
        client = SchoFeeClient()
        page_size = min(100, max(1, options["page_size"]))

        try:
            courses_data = client.list_courses(page=1, page_size=page_size)
        except SchoFeeAPIError as e:
            self.stdout.write(self.style.ERROR(f"Failed to fetch courses: HTTP {e.status_code} ({e.error_code}) - {e.message}"))
            return
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Unexpected error: {e}"))
            return

        items = courses_data.get("items", [])
        total = courses_data.get("totalCount", len(items))
        self.stdout.write(f"Fetched {len(items)} course(s) from SchoFee (total in catalog: {total}).")

        created_count = 0
        updated_count = 0

        for item in items:
            c_id = item.get("id")
            c_name = item.get("courseName") or "Unnamed Course"
            c_code = item.get("courseCode") or ""
            c_fees = Decimal(str(item.get("courseFees") or 0))
            max_emi = int(item.get("maxEmiMonths") or 12)

            if not c_id:
                continue

            # Attempt simple auto-slug matching
            matched_slug = ""
            name_lower = c_name.lower()
            if "cseet" in name_lower:
                matched_slug = "cseet"
            elif "executive" in name_lower:
                matched_slug = "cs_executive"
            elif "professional" in name_lower:
                matched_slug = "cs_professional"

            obj, created = CourseMapping.objects.update_or_create(
                schofee_course_id=c_id,
                defaults={
                    "schofee_course_name": c_name,
                    "schofee_course_code": c_code,
                    "schofee_course_fees": c_fees,
                    "max_emi_months": max_emi,
                    "is_active": True,
                    **({"local_course_slug": matched_slug} if matched_slug else {}),
                },
            )

            if created:
                created_count += 1
            else:
                updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Sync complete! Created: {created_count}, Updated: {updated_count} CourseMapping record(s)."
            )
        )
