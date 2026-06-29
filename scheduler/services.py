# scheduler/services.py

"""
TaskScheduler — central service for DB-persisted background tasks.

Usage:
    from scheduler.services import TaskScheduler

    # one-shot delayed task
    TaskScheduler.schedule(
        task_type="interview_feedback_reminder",
        task_kwargs={"booking_id": str(booking.id)},
        delay_seconds=7200,
    )

    # recurring task
    TaskScheduler.schedule(
        task_type="bgv_status_poll",
        delay_seconds=0,
        is_recurring=True,
        interval_seconds=3600,
    )
"""

import logging
import threading
from datetime import timedelta
from typing import Optional

from django.utils import timezone

logger = logging.getLogger(__name__)


class TaskScheduler:
    """
    Manages DB-persisted scheduled tasks with in-process execution.

    - ``schedule()``    → create DB row + start an in-memory timer
    - ``cancel()``      → mark matching pending tasks as cancelled
    - ``reconcile()``   → re-schedule all incomplete/missed tasks from DB
    - ``register()``    → map a *task_type* string to a callable
    """

    # task_type → callable
    _registry: dict = {}

    # task IDs that have been armed in-memory in this process lifetime.
    # Used to prevent reconcile/reschedule_future_pending from double-arming
    # tasks that schedule() already armed.
    _armed_task_ids: set = set()

    # ── Registration ─────────────────────────────────────────────

    @classmethod
    def register(cls, task_type: str, fn):
        """Register a callable under *task_type*."""
        cls._registry[task_type] = fn
        logger.info("[SCHEDULER] Registered task type: %s", task_type)

    # ── Scheduling ───────────────────────────────────────────────

    @classmethod
    def schedule(
        cls,
        task_type: str,
        task_kwargs: Optional[dict] = None,
        delay_seconds: int = 0,
        is_recurring: bool = False,
        interval_seconds: Optional[int] = None,
        max_retries: int = 3,
    ):
        """
        Persist a new task to the DB and schedule it in memory.

        For recurring tasks that should be singletons (e.g. BGV poll),
        this skips creation if a pending task of the same type already exists.
        """
        from .models import ScheduledTask

        task_kwargs = task_kwargs or {}

        # ── Singleton guard for recurring tasks ───────────
        if is_recurring:
            existing_qs = ScheduledTask.objects.filter(
                task_type=task_type,
                status__in=["pending", "running"],
            )
            if task_kwargs:
                existing_qs = existing_qs.filter(task_kwargs=task_kwargs)
            else:
                existing_qs = existing_qs.filter(task_kwargs__in=[{}, None])

            if existing_qs.exists():
                logger.info(
                    "[SCHEDULER] Recurring task '%s' with kwargs %s already pending/running — skipped.",
                    task_type, task_kwargs
                )
                return None

        scheduled_at = timezone.now() + timedelta(seconds=delay_seconds)

        task = ScheduledTask.objects.create(
            task_type=task_type,
            task_kwargs=task_kwargs,
            status="pending",
            scheduled_at=scheduled_at,
            is_recurring=is_recurring,
            interval_seconds=interval_seconds,
            max_retries=max_retries,
        )

        print(
            f"[SCHEDULER] Created task {task.id} "
            f"type={task_type} delay={delay_seconds}s "
            f"recurring={is_recurring}"
        )

        cls._schedule_in_memory(task.id, max(delay_seconds, 0))
        return task

    # ── Cancellation ─────────────────────────────────────────────

    @classmethod
    def cancel(cls, task_type: str, task_kwargs_filter: Optional[dict] = None):
        """
        Cancel all *pending* tasks that match *task_type*.

        If *task_kwargs_filter* is supplied, only tasks whose ``task_kwargs``
        is a superset of the filter dict are cancelled.
        """
        from .models import ScheduledTask

        qs = ScheduledTask.objects.filter(
            task_type=task_type,
            status="pending",
        )

        if task_kwargs_filter:
            # JSONField containment lookup
            qs = qs.filter(task_kwargs__contains=task_kwargs_filter)

        count = qs.update(status="cancelled", updated_at=timezone.now())
        if count:
            print(f"[SCHEDULER] Cancelled {count} pending '{task_type}' task(s).")
        return count

    # ── Execution ────────────────────────────────────────────────

    @classmethod
    def _execute(cls, task_id):
        """
        Called by TASK_QUEUE workers.  Loads the DB row, runs the
        registered function, and updates the status accordingly.
        """
        from django.db import transaction
        from .models import ScheduledTask

        with transaction.atomic():
            try:
                # Use select_for_update to lock the row and skip if another worker already grabbed it
                task = ScheduledTask.objects.select_for_update(skip_locked=True).get(id=task_id)
            except ScheduledTask.DoesNotExist:
                logger.warning("[SCHEDULER] Task %s not found in DB or already locked — skipping.", task_id)
                return

            # ── Guard: skip if already cancelled, completed, or running ────────
            if task.status in ("cancelled", "completed", "running"):
                print(f"[SCHEDULER] Task {task_id} is {task.status} — skipping execution.")
                return

            fn = cls._registry.get(task.task_type)
            if fn is None:
                logger.error(
                    "[SCHEDULER] No registered function for task_type='%s'",
                    task.task_type,
                )
                task.status = "failed"
                task.error_message = f"Unknown task_type: {task.task_type}"
                task.save(update_fields=["status", "error_message", "updated_at"])
                return

            # ── Mark running ─────────────────────────────────────────
            task.status = "running"
            task.started_at = timezone.now()
            task.save(update_fields=["status", "started_at", "updated_at"])

        # Execute OUTSIDE the transaction so we don't hold the lock for the entire duration
        # of the task (which could be a long-running API call)

        try:
            print(f"[SCHEDULER] Executing task {task_id} ({task.task_type})...")
            fn(**task.task_kwargs)

            # ── Success ──────────────────────────────────────────
            task.status = "completed"
            task.completed_at = timezone.now()
            task.save(update_fields=["status", "completed_at", "updated_at"])
            print(f"[SCHEDULER] Task {task_id} completed successfully.")

        except Exception as exc:
            logger.exception(
                "[SCHEDULER] Task %s (%s) failed: %s",
                task_id, task.task_type, exc,
            )
            task.retry_count += 1

            if task.retry_count < task.max_retries:
                # ── Retry with exponential backoff ───────────────
                backoff = 2 ** task.retry_count
                task.status = "pending"
                task.scheduled_at = timezone.now() + timedelta(seconds=backoff)
                task.error_message = str(exc)
                task.save(update_fields=[
                    "status", "retry_count", "scheduled_at",
                    "error_message", "updated_at",
                ])
                print(
                    f"[SCHEDULER] Task {task_id} will retry "
                    f"({task.retry_count}/{task.max_retries}) in {backoff}s"
                )
                cls._schedule_in_memory(task_id, backoff)
                return  # Don't reschedule recurring yet
            else:
                task.status = "failed"
                task.error_message = str(exc)
                task.save(update_fields=[
                    "status", "retry_count", "error_message", "updated_at",
                ])
                print(f"[SCHEDULER] Task {task_id} failed permanently after {task.max_retries} retries.")

        # ── Recurring: schedule the next iteration ───────────────
        if task.is_recurring and task.interval_seconds:
            print(
                f"[SCHEDULER] Recurring task '{task.task_type}' — "
                f"scheduling next run in {task.interval_seconds}s"
            )
            cls.schedule(
                task_type=task.task_type,
                task_kwargs=task.task_kwargs if task.task_kwargs else None,
                delay_seconds=task.interval_seconds,
                is_recurring=True,
                interval_seconds=task.interval_seconds,
                max_retries=task.max_retries,
            )

    # ── Reconciliation ───────────────────────────────────────────

    @classmethod
    def reconcile(cls):
        """
        Query DB for tasks that should have run but didn't (e.g. after
        a restart).  Re-schedule them in memory with zero delay.
        """
        from .models import ScheduledTask

        now = timezone.now()

        # Tasks that were pending and their time has passed
        missed_pending = list(
            ScheduledTask.objects.filter(
                status="pending",
                scheduled_at__lte=now,
            ).values_list("id", flat=True)
        )

        # Tasks stuck in 'running' (process died mid-execution)
        stuck_running = list(
            ScheduledTask.objects.filter(
                status="running",
            ).values_list("id", flat=True)
        )

        # Reset stuck tasks to pending so _execute picks them up
        if stuck_running:
            ScheduledTask.objects.filter(
                id__in=stuck_running,
            ).update(status="pending", updated_at=now)

        all_ids = missed_pending + stuck_running
        if not all_ids:
            print("[SCHEDULER] Reconciliation: no missed/stuck tasks found.")
            return

        print(
            f"[SCHEDULER] Reconciliation: re-scheduling {len(all_ids)} task(s) "
            f"({len(missed_pending)} missed, {len(stuck_running)} stuck)."
        )

        for task_id in all_ids:
            if task_id in cls._armed_task_ids:
                logger.info("[SCHEDULER] Reconcile: task %s already armed — skipped.", task_id)
                continue
            cls._schedule_in_memory(task_id, delay_seconds=0)

    # ── Future pending tasks ─────────────────────────────────────

    @classmethod
    def reschedule_future_pending(cls):
        """
        On startup, also re-arm timers for tasks that are pending but
        whose scheduled_at is in the future (they had timers that were
        lost on restart).
        """
        from .models import ScheduledTask

        now = timezone.now()
        future_tasks = list(
            ScheduledTask.objects.filter(
                status="pending",
                scheduled_at__gt=now,
            ).values_list("id", "scheduled_at")
        )

        if not future_tasks:
            print("[SCHEDULER] No future pending tasks to re-arm.")
            return

        print(
            f"[SCHEDULER] Re-arming {len(future_tasks)} future pending task(s)."
        )
        for task_id, scheduled_at in future_tasks:
            if task_id in cls._armed_task_ids:
                logger.info("[SCHEDULER] Future re-arm: task %s already armed — skipped.", task_id)
                continue
            delay = max((scheduled_at - now).total_seconds(), 0)
            cls._schedule_in_memory(task_id, delay)

    # ── In-memory scheduling ─────────────────────────────────────

    @classmethod
    def _schedule_in_memory(cls, task_id, delay_seconds: float):
        """
        Create a daemon ``threading.Timer`` that enqueues ``_execute``
        into the global TASK_QUEUE after *delay_seconds*.
        """
        from core.task_queue import TASK_QUEUE

        # Track that we've armed this task in this process lifetime
        cls._armed_task_ids.add(task_id)

        def _enqueue():
            # Remove from armed set so it can be re-armed after execution
            cls._armed_task_ids.discard(task_id)
            TASK_QUEUE.enqueue(cls._execute, task_id)

        if delay_seconds <= 0:
            # Execute immediately
            _enqueue()
        else:
            timer = threading.Timer(delay_seconds, _enqueue)
            timer.daemon = True
            timer.start()
