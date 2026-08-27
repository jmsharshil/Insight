# scheduler/apps.py

import os
import sys
import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class SchedulerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "scheduler"
    _started = False  # Class-level flag to prevent duplicate starts

    def ready(self):
        # Prevent during tests or management commands that run before DB is ready
        if any(cmd in sys.argv for cmd in ("test", "makemigrations", "migrate", "check", "showmigrations")):
            return

        # Prevent duplicate starts
        if SchedulerConfig._started:
            return

        # Only in the main process
        run_main = os.environ.get("RUN_MAIN")
        werkzeug_main = os.environ.get("WERKZEUG_RUN_MAIN")

        is_main_process = (
            run_main == "true"
            or werkzeug_main == "true"
            or (run_main is None and werkzeug_main is None)
        )

        if not is_main_process:
            print("[SCHEDULER APP] Not main process — skipping startup.")
            return

        SchedulerConfig._started = True
        print("[SCHEDULER APP] Initialising persistent task scheduler...")

        # ── Register all known task types ────────────────────────
        self._register_tasks()

        # ── Reconcile incomplete tasks from DB ───────────────────
        # Use on_commit or a short delay to ensure DB is ready
        from django.db import connection
        from core.task_queue import TASK_QUEUE

        def _startup_reconcile():
            """Run reconciliation + re-arm future timers on startup."""
            from .services import TaskScheduler

            print("[SCHEDULER APP] Running startup reconciliation...")

            # ── Ensure recurring system tasks exist FIRST ────────
            # Must run before reconcile() so the singleton guard blocks
            # duplicate creation when reconcile() completes an existing task.
            self._ensure_recurring_tasks()

            # ── Reconcile missed/stuck tasks from DB ─────────────
            TaskScheduler.reconcile()
            TaskScheduler.reschedule_future_pending()

            # ── Start periodic reconciliation (every 30 minutes) ─
            self._start_periodic_reconciliation()

            print("[SCHEDULER APP] Startup complete.")

        # Enqueue so it runs after Django is fully loaded
        TASK_QUEUE.enqueue(_startup_reconcile)

    def _register_tasks(self):
        """Register all task_type → callable mappings."""
        from .services import TaskScheduler

        # register the scheduled tasks here
        from leave.tasks import accrue_monthly_leaves_task
        from exams.tasks import (
            update_exam_statuses,
            send_pending_submission_reminders,
            auto_expire_exam_sessions,
            send_exam_material_upload_reminders,
        )
        from auditlog.tasks import cleanup_old_audit_logs
        from auth_user.tasks import cleanup_old_notifications
        from attendance.tasks import (
            detect_missing_scans_all_branches,
            auto_mark_student_absentees,
        )
        TaskScheduler.register(
            "accrue_monthly_leaves",
            lambda: accrue_monthly_leaves_task()
        )
        TaskScheduler.register("update_exam_statuses", update_exam_statuses)
        TaskScheduler.register("send_pending_submission_reminders", send_pending_submission_reminders)
        TaskScheduler.register("auto_expire_exam_sessions", auto_expire_exam_sessions)
        TaskScheduler.register("send_exam_material_upload_reminders", send_exam_material_upload_reminders)
        TaskScheduler.register("cleanup_old_audit_logs", cleanup_old_audit_logs)
        TaskScheduler.register("cleanup_old_notifications", cleanup_old_notifications)
        TaskScheduler.register("detect_missing_scans_all_branches", detect_missing_scans_all_branches)
        TaskScheduler.register("auto_mark_student_absentees", auto_mark_student_absentees)
        print("[SCHEDULER APP] All task types registered.")

    @staticmethod
    def _seconds_until_target_ist(hour, minute=0):
        """
        Calculate seconds from now until the next occurrence of
        the given hour:minute in IST (Asia/Kolkata).

        If the target time has already passed today, it returns the
        delay until the same time tomorrow.

        Compatible with Python 3.8+ (uses django.utils.timezone
        instead of zoneinfo).
        """
        import datetime
        from django.utils import timezone as tz

        # timezone.localtime() uses settings.TIME_ZONE ('Asia/Kolkata')
        now_ist = tz.localtime(tz.now())

        target_today = now_ist.replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )

        if now_ist < target_today:
            delay = (target_today - now_ist).total_seconds()
        else:
            # Target time already passed today → schedule for tomorrow
            target_tomorrow = target_today + datetime.timedelta(days=1)
            delay = (target_tomorrow - now_ist).total_seconds()

        return int(delay)

    def _ensure_recurring_tasks(self):
        """
        Make sure each recurring system task has at least one pending row.
        If not (fresh deploy or all completed), create one.

        For wall-clock-sensitive tasks (like detect_missing_scans_all_branches),
        any existing pending task is cancelled and re-created with the correct
        delay to the target IST time, so that server restarts always self-correct.
        """
        from .services import TaskScheduler
        from .models import ScheduledTask
        from django.utils import timezone

        # ── Fix detect_missing_scans_all_branches timing ─────────
        # Cancel any existing pending task so we can re-create it
        # with the correct delay to 8:30 AM IST.  Without this,
        # the singleton guard would keep the OLD task (which was
        # scheduled at the wrong time from a previous deploy).
        stale = ScheduledTask.objects.filter(
            task_type="detect_missing_scans_all_branches",
            status="pending",
        )
        stale_count = stale.count()
        if stale_count:
            stale.update(status="cancelled", updated_at=timezone.now())
            print(
                f"[SCHEDULER APP] Cancelled {stale_count} stale "
                f"detect_missing_scans_all_branches task(s) to re-schedule at correct time."
            )

        detect_missing_scans_delay = self._seconds_until_target_ist(8, 30)
        print(
            f"[SCHEDULER APP] detect_missing_scans_all_branches "
            f"scheduled in {detect_missing_scans_delay}s "
            f"(next 08:30 AM IST)"
        )

        RECURRING_TASKS = [
            {
                "task_type": "accrue_monthly_leaves",
                "interval_seconds": 86400,       # 24 hours (daily)
                "delay_seconds": 60,             # first run after 60s
                "max_retries": 3,
            },
            {
                "task_type": "update_exam_statuses",
                "interval_seconds": 60,          # every minute
                "delay_seconds": 30,
                "max_retries": 3,
            },
            {
                "task_type": "auto_expire_exam_sessions",
                "interval_seconds": 60,          # every minute
                "delay_seconds": 45,
                "max_retries": 3,
            },
            {
                "task_type": "send_pending_submission_reminders",
                "interval_seconds": 86400,       # daily
                "delay_seconds": 300,            # 5 min after startup
                "max_retries": 5,
            },
            {
                "task_type": "cleanup_old_audit_logs",
                "interval_seconds": 86400,       # daily
                "delay_seconds": 1800,           # 30 min after startup
                "max_retries": 3,
            },
            {
                "task_type": "cleanup_old_notifications",
                "interval_seconds": 86400,       # daily
                "delay_seconds": 1800,           # 30 min after startup
                "max_retries": 3,
            },
            {
                "task_type": "detect_missing_scans_all_branches",
                "interval_seconds": 86400,       # daily (every 24h)
                "delay_seconds": detect_missing_scans_delay,  # next 08:30 AM IST
                "max_retries": 3,
            },
            {
                "task_type": "send_exam_material_upload_reminders",
                "interval_seconds": 86400,       # daily
                "delay_seconds": 600,            # 10 min after startup
                "max_retries": 3,
            },
            {
                "task_type": "auto_mark_student_absentees",
                "interval_seconds": 600,         # every 10 minutes
                "delay_seconds": 120,            # 2 min after startup (let DB settle first)
                "max_retries": 3,
            },
        ]

        for cfg in RECURRING_TASKS:
            TaskScheduler.schedule(
                task_type=cfg["task_type"],
                delay_seconds=cfg["delay_seconds"],
                is_recurring=True,
                interval_seconds=cfg["interval_seconds"],
                max_retries=cfg["max_retries"],
            )

    def _start_periodic_reconciliation(self):
        """
        Every 30 minutes, run reconcile() to catch any missed tasks
        (e.g. timers that silently failed, DB rows from external tools).
        """
        import threading
        from .services import TaskScheduler
        from core.task_queue import TASK_QUEUE

        RECONCILE_INTERVAL = 1800  # 30 minutes

        def _reconcile_loop():
            TASK_QUEUE.enqueue(TaskScheduler.reconcile)
            # Re-arm
            timer = threading.Timer(RECONCILE_INTERVAL, _reconcile_loop)
            timer.daemon = True
            timer.start()

        timer = threading.Timer(RECONCILE_INTERVAL, _reconcile_loop)
        timer.daemon = True
        timer.start()
        print(
            f"[SCHEDULER APP] Periodic reconciliation armed "
            f"(every {RECONCILE_INTERVAL}s)."
        )
