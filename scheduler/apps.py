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
        # Prevent during tests
        if "test" in sys.argv:
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
        TaskScheduler.register(
            "accrue_monthly_leaves",
            lambda: accrue_monthly_leaves_task()
        )
        print("[SCHEDULER APP] All task types registered.")

    def _ensure_recurring_tasks(self):
        """
        Make sure each recurring system task has at least one pending row.
        If not (fresh deploy or all completed), create one.
        """
        from .services import TaskScheduler

        RECURRING_TASKS = [
            {
                "task_type": "accrue_monthly_leaves",
                "interval_seconds": 86400,       # 24 hours (daily)
                "delay_seconds": 60,             # first run after 60s
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
