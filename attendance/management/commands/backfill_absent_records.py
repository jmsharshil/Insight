import datetime
import logging
from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Backfill absent AttendanceRecord entries for no_show violation dates."

    def add_arguments(self, parser):
        parser.add_argument("--dates", nargs="+", type=str, required=True,
                            help="One or more dates in YYYY-MM-DD format to backfill.")
        parser.add_argument("--student-id", type=str, default=None,
                            help="Optional: restrict backfill to a single student UUID.")
        parser.add_argument("--dry-run", action="store_true", default=False,
                            help="Print what would be created without writing to DB.")

    def handle(self, *args, **options):
        from attendance.models import AttendanceRecord, ViolationRecord
        from batches.models import TimetableSlot

        dates_raw = options["dates"]
        student_id_filter = options.get("student_id")
        dry_run = options["dry_run"]

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - no records will be written."))

        total_created = 0

        for date_str in dates_raw:
            try:
                date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                self.stderr.write("Invalid date: {} - skip.".format(date_str))
                continue

            processing_dow = date_obj.weekday()

            violations_qs = ViolationRecord.objects.filter(
                violation_type="no_show",
                date=date_obj,
            ).select_related("student", "student__branch")

            if student_id_filter:
                violations_qs = violations_qs.filter(student_id=student_id_filter)

            if not violations_qs.exists():
                self.stdout.write("{}: no no_show violations - skip.".format(date_str))
                continue

            self.stdout.write("{}: {} violation(s)...".format(date_str, violations_qs.count()))

            for violation in violations_qs:
                student = violation.student
                if not student:
                    continue

                enrolled_batch_ids = list(
                    student.batch_enrollments.values_list("batch_id", flat=True)
                )
                primary_batch_id = (
                    getattr(student, "current_batch_id", None)
                    or getattr(student, "batch_id", None)
                )
                if primary_batch_id and primary_batch_id not in enrolled_batch_ids:
                    enrolled_batch_ids.append(primary_batch_id)

                if not enrolled_batch_ids:
                    self.stdout.write("  Student {}: no batches - skip.".format(student.id))
                    continue

                slots = TimetableSlot.objects.filter(
                    Q(day_of_week=processing_dow) | Q(session_date=date_obj),
                    batch_id__in=enrolled_batch_ids,
                    start_time__isnull=False,
                ).select_related("batch", "batch__branch")

                if not slots.exists():
                    self.stdout.write(
                        "  Student {}: no slots DOW={} - skip.".format(student.id, processing_dow)
                    )
                    continue

                absent_records = []
                for slot in slots:
                    already_exists = AttendanceRecord.objects.filter(
                        student=student,
                        date=date_obj,
                        timetable_slot=slot,
                    ).exists()
                    if already_exists:
                        continue

                    slot_batch = slot.batch
                    slot_branch_id = (
                        slot_batch.branch_id
                        if slot_batch and slot_batch.branch_id
                        else (student.branch_id if student.branch_id else None)
                    )

                    absent_records.append(
                        AttendanceRecord(
                            student=student,
                            date=date_obj,
                            timetable_slot=slot,
                            batch=slot_batch,
                            branch_id=slot_branch_id,
                            status="absent",
                            checked_in_at=None,
                            checked_out_at=None,
                            marked_by=None,
                        )
                    )

                if absent_records:
                    if not dry_run:
                        AttendanceRecord.objects.bulk_create(
                            absent_records, ignore_conflicts=True
                        )
                    total_created += len(absent_records)
                    verb = "[DRY RUN] Would create" if dry_run else "Created"
                    self.stdout.write(self.style.SUCCESS(
                        "  {} {} absent record(s) for student {} on {}.".format(
                            verb, len(absent_records), student.id, date_str
                        )
                    ))
                else:
                    self.stdout.write(
                        "  Student {}: records already exist - skip.".format(student.id)
                    )

        label = "DRY RUN complete" if dry_run else "Backfill complete"
        self.stdout.write(self.style.SUCCESS(
            "\n{} - {} record(s).".format(label, total_created)
        ))
