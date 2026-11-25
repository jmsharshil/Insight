"""
schofee_finance/management/commands/schofee_smoke_test.py
─────────────────────────────────────────────────────────
Diagnostic management command to verify SchoFee API connectivity against staging.
Calls:
1. Token exchange (/v1/oauth/token)
2. Courses list (/v1/courses)
3. Supported banks list (/v1/banks)

Prints status codes and summary counts only. NEVER logs or prints secrets, tokens, or personal data.
"""

from django.core.management.base import BaseCommand
from schofee_finance.services.client import SchoFeeClient
from schofee_finance.services.token import token_service
from schofee_finance.services.exceptions import SchoFeeAPIError


class Command(BaseCommand):
    help = "Performs a diagnostic smoke test against the SchoFee B2B API."

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("=== SchoFee B2B API Smoke Test ==="))
        client = SchoFeeClient()

        # 1. Test OAuth Token Exchange
        self.stdout.write("1. Testing OAuth Token Exchange (/v1/oauth/token)...")
        try:
            token = token_service.get_token(force_refresh=True)
            if token and len(token) > 10:
                self.stdout.write(
                    self.style.SUCCESS(f"   [OK] HTTP 200 - Token received successfully (Length: {len(token)} chars)")
                )
            else:
                self.stdout.write(self.style.ERROR("   [FAIL] Token received is empty or invalid."))
                return
        except SchoFeeAPIError as e:
            self.stdout.write(self.style.ERROR(f"   [FAIL] Token error: HTTP {e.status_code} ({e.error_code})"))
            return
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"   [FAIL] Unexpected token error: {e}"))
            return

        # 2. Test Courses endpoint
        self.stdout.write("2. Testing Courses List (/v1/courses)...")
        try:
            courses_data = client.list_courses(page=1, page_size=5)
            items = courses_data.get("items", [])
            total = courses_data.get("totalCount", len(items))
            self.stdout.write(
                self.style.SUCCESS(
                    f"   [OK] HTTP 200 - Courses retrieved successfully. Returned {len(items)} items (total: {total})"
                )
            )
        except SchoFeeAPIError as e:
            self.stdout.write(self.style.WARNING(f"   [FAIL] Courses error: HTTP {e.status_code} ({e.error_code})"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"   [FAIL] Unexpected courses error: {e}"))

        # 3. Test Banks endpoint
        self.stdout.write("3. Testing Banks List (/v1/banks)...")
        try:
            banks_data = client.list_banks()
            items = banks_data.get("items", [])
            self.stdout.write(
                self.style.SUCCESS(
                    f"   [OK] HTTP 200 - Banks retrieved successfully. Returned {len(items)} bank institutions"
                )
            )
        except SchoFeeAPIError as e:
            self.stdout.write(self.style.WARNING(f"   [FAIL] Banks error: HTTP {e.status_code} ({e.error_code})"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"   [FAIL] Unexpected banks error: {e}"))

        self.stdout.write(self.style.MIGRATE_HEADING("=== Smoke Test Finished ==="))
