# leads/tasks.py

import logging
from datetime import timedelta
from django.utils import timezone
from .models import SalesDailyPlan, SalesPlanReminder
from chat.notifications import send_system_notification, send_whatsapp_with_fallback

logger = logging.getLogger(__name__)


def send_sales_plan_reminders():
    """
    Daily background task (scheduled to run at 8:00 AM IST).
    Sends WhatsApp and in-app system notifications to salespeople:
      1. 2 days before an event (for plans happening in 2 days).
      2. 1 day before an event (for tomorrow's plans).
      3. The day of the event (for today's plans).
      
    NOTE: As per user request, this has been disabled to prefer custom reminders.
    """
    
    today = timezone.localdate()
    tomorrow = today + timedelta(days=1)
    day_after_tomorrow = today + timedelta(days=2)

    two_days_count = 0
    tomorrow_count = 0
    today_count = 0

    # ── 1. Reminders 2 days before the event ─────────────────────────────────
    plans_two_days = SalesDailyPlan.objects.filter(
        plan_date=day_after_tomorrow,
        reminder_two_days_before_sent=False,
    ).select_related('user')

    for plan in plans_two_days:
        if not plan.user:
            continue

        place_str = f" at {plan.place}" if plan.place else ""
        time_str = ""
        if plan.start_time and plan.end_time:
            time_str = f" from {plan.start_time.strftime('%I:%M %p')} to {plan.end_time.strftime('%I:%M %p')}"
        elif plan.start_time:
            time_str = f" at {plan.start_time.strftime('%I:%M %p')}"

        desc_str = f"\nAgenda: {plan.description}" if plan.description else ""
        event_name = plan.type or "Sales Event"

        title = f"Upcoming Event in 2 Days: {event_name}"
        body = (
            f"Reminder: You have an upcoming event in 2 days ({plan.plan_date.strftime('%d %b %Y')}): "
            f"{event_name}{place_str}{time_str}.{desc_str}"
        )

        try:
            send_system_notification(
                user_id=str(plan.user.id),
                title=title,
                body=body,
                metadata={
                    'plan_id': str(plan.id),
                    'type': 'sales_plan_reminder',
                    'plan_date': str(plan.plan_date),
                    'reminder_type': 'two_days_before',
                },
                notification_type='sales',
            )
        except Exception as e:
            logger.error(f"Failed to send 2-day system notification for plan {plan.id}: {e}")

        if getattr(plan.user, 'phone', None):
            try:
                send_whatsapp_with_fallback(
                    to=plan.user.phone,
                    fallback_body=body,
                    user_id=str(plan.user.id),
                )
            except Exception as e:
                logger.error(f"Failed to send 2-day WhatsApp reminder for plan {plan.id}: {e}")

        plan.reminder_two_days_before_sent = True
        plan.save(update_fields=['reminder_two_days_before_sent'])
        two_days_count += 1

    # ── 2. Reminders 1 day before the event ──────────────────────────────────
    plans_tomorrow = SalesDailyPlan.objects.filter(
        plan_date=tomorrow,
        reminder_one_day_before_sent=False,
    ).select_related('user')

    for plan in plans_tomorrow:
        if not plan.user:
            continue

        place_str = f" at {plan.place}" if plan.place else ""
        time_str = ""
        if plan.start_time and plan.end_time:
            time_str = f" from {plan.start_time.strftime('%I:%M %p')} to {plan.end_time.strftime('%I:%M %p')}"
        elif plan.start_time:
            time_str = f" at {plan.start_time.strftime('%I:%M %p')}"

        desc_str = f"\nAgenda: {plan.description}" if plan.description else ""
        event_name = plan.type or "Sales Event"

        title = f"Upcoming Event Tomorrow: {event_name}"
        body = (
            f"Reminder: You have an upcoming event tomorrow ({plan.plan_date.strftime('%d %b %Y')}): "
            f"{event_name}{place_str}{time_str}.{desc_str}"
        )

        try:
            send_system_notification(
                user_id=str(plan.user.id),
                title=title,
                body=body,
                metadata={
                    'plan_id': str(plan.id),
                    'type': 'sales_plan_reminder',
                    'plan_date': str(plan.plan_date),
                    'reminder_type': 'one_day_before',
                },
                notification_type='sales',
            )
        except Exception as e:
            logger.error(f"Failed to send system notification for plan {plan.id}: {e}")

        if getattr(plan.user, 'phone', None):
            try:
                send_whatsapp_with_fallback(
                    to=plan.user.phone,
                    fallback_body=body,
                    user_id=str(plan.user.id),
                )
            except Exception as e:
                logger.error(f"Failed to send WhatsApp reminder for plan {plan.id}: {e}")

        plan.reminder_one_day_before_sent = True
        plan.save(update_fields=['reminder_one_day_before_sent'])
        tomorrow_count += 1

    # ── 3. Reminders on the day of the event ─────────────────────────────────
    plans_today = SalesDailyPlan.objects.filter(
        plan_date=today,
        reminder_day_of_event_sent=False,
    ).select_related('user')

    for plan in plans_today:
        if not plan.user:
            continue

        place_str = f" at {plan.place}" if plan.place else ""
        time_str = ""
        if plan.start_time and plan.end_time:
            time_str = f" from {plan.start_time.strftime('%I:%M %p')} to {plan.end_time.strftime('%I:%M %p')}"
        elif plan.start_time:
            time_str = f" at {plan.start_time.strftime('%I:%M %p')}"

        desc_str = f"\nAgenda: {plan.description}" if plan.description else ""
        event_name = plan.type or "Sales Event"

        title = f"Today's Event Reminder: {event_name}"
        body = (
            f"Reminder: You have an event scheduled for today: "
            f"{event_name}{place_str}{time_str}.{desc_str}"
        )

        try:
            send_system_notification(
                user_id=str(plan.user.id),
                title=title,
                body=body,
                metadata={
                    'plan_id': str(plan.id),
                    'type': 'sales_plan_reminder',
                    'plan_date': str(plan.plan_date),
                    'reminder_type': 'day_of_event',
                },
                notification_type='sales',
            )
        except Exception as e:
            logger.error(f"Failed to send system notification for plan {plan.id}: {e}")

        if getattr(plan.user, 'phone', None):
            try:
                send_whatsapp_with_fallback(
                    to=plan.user.phone,
                    fallback_body=body,
                    user_id=str(plan.user.id),
                )
            except Exception as e:
                logger.error(f"Failed to send WhatsApp reminder for plan {plan.id}: {e}")

        plan.reminder_day_of_event_sent = True
        plan.save(update_fields=['reminder_day_of_event_sent'])
        today_count += 1

    logger.info(
        f"[SALES REMINDERS] Sent {two_days_count} 2-day-before, "
        f"{tomorrow_count} 1-day-before, and {today_count} day-of-event reminders."
    )
    return {
        'two_days_reminders': two_days_count,
        'tomorrow_reminders': tomorrow_count,
        'today_reminders': today_count,
    }


def auto_start_sales_activities():
    """
    Background task to auto-start activities based on their plan's start time.
    Runs every minute.
    """
    now = timezone.now()
    today = timezone.localdate(now)
    current_time = now.time()

    from .models import SalesDailyActivity
    
    pending_activities = SalesDailyActivity.objects.filter(
        activity_date=today,
        status='pending',
        plan__isnull=False,
        plan__start_time__lte=current_time
    )
    
    count = 0
    for activity in pending_activities:
        activity.status = 'ongoing'
        activity.save(update_fields=['status', 'updated_at'])
        count += 1
        
    if count > 0:
        logger.info(f"[SALES AUTO-START] Auto-started {count} sales activities based on plan start time.")
        
    return {'auto_started_activities': count}


def send_custom_sales_plan_reminders():
    """
    Background task to process custom sales plan reminders.
    Runs every minute.
    """
    now = timezone.now()
    reminders = SalesPlanReminder.objects.filter(is_sent=False, reminder_time__lte=now).select_related('plan', 'plan__user')
    
    sent_count = 0
    for reminder in reminders:
        plan = reminder.plan
        if not plan or not plan.user:
            continue
            
        place_str = f" at {plan.place}" if plan.place else ""
        time_str = ""
        if plan.start_time and plan.end_time:
            time_str = f" from {plan.start_time.strftime('%I:%M %p')} to {plan.end_time.strftime('%I:%M %p')}"
        elif plan.start_time:
            time_str = f" at {plan.start_time.strftime('%I:%M %p')}"

        desc_str = f"\nAgenda: {plan.description}" if plan.description else ""
        event_name = plan.type or "Sales Event"
        purpose_str = f"\nPurpose: {reminder.purpose}" if reminder.purpose else ""

        title = f"Sales Plan Reminder: {event_name}"
        if reminder.purpose:
            title += f" - {reminder.purpose}"
            
        body = (
            f"Reminder: You have a scheduled event ({plan.plan_date.strftime('%d %b %Y')}): "
            f"{event_name}{place_str}{time_str}.{desc_str}{purpose_str}"
        )

        # Send system notification
        try:
            send_system_notification(
                user_id=str(plan.user.id),
                title=title,
                body=body,
                metadata={
                    'plan_id': str(plan.id),
                    'reminder_id': str(reminder.id),
                    'type': 'sales_plan_custom_reminder',
                    'plan_date': str(plan.plan_date),
                },
                notification_type='sales',
            )
        except Exception as e:
            logger.error(f"Failed to send system notification for custom reminder {reminder.id}: {e}")

        # Send WhatsApp
        if getattr(plan.user, 'phone', None):
            try:
                send_whatsapp_with_fallback(
                    to=plan.user.phone,
                    fallback_body=body,
                    user_id=str(plan.user.id),
                )
            except Exception as e:
                logger.error(f"Failed to send WhatsApp custom reminder for {reminder.id}: {e}")

        # Mark as sent
        reminder.is_sent = True
        reminder.save(update_fields=['is_sent'])
        sent_count += 1
        
    if sent_count > 0:
        logger.info(f"[SALES REMINDERS] Sent {sent_count} custom reminders.")
        
    return {'sent_custom_reminders': sent_count}


def auto_mark_sales_attendance(target_date=None):
    """
    End-of-day background task (schedule at 11:55 PM IST).

    For every sales user who has a SalesDailyActivity on `target_date`
    but does NOT yet have an EmployeeAttendanceRecord for that date, this
    task auto-creates a geo-based attendance record using the GPS coordinates
    captured in their field photos.

    Logic:
    - start_selfie photo  → use as check-in time & location
    - end_selfie photo    → use as check-out time
    - If neither selfie exists, fall back to first/last activity photo GPS
    - Marks location_verified=False (geo only, no QR)
    - Shortfall is calculated as max(0, 540 - duration_minutes) for non-exempt roles

    This ensures sales staff who are in the field all day but don't QR-scan
    at the branch are still marked present with their actual field GPS.
    """
    from .models import SalesDailyActivity
    from attendance.models import EmployeeAttendanceRecord
    from core.utils import get_user_branch_id
    from branch.models import Branch

    date = target_date or timezone.localdate()
    marked_count = 0
    skipped_count = 0

    # Find all sales activities for the target date
    activities = SalesDailyActivity.objects.filter(
        activity_date=date,
    ).select_related('user').prefetch_related('photos')

    # Group by user — we only need to create one attendance record per user per day
    processed_users = set()

    for activity in activities:
        user = activity.user
        if not user or user.id in processed_users:
            continue
        processed_users.add(user.id)

        # Skip if attendance already recorded for this user today (QR, selfie, or manual)
        already_recorded = EmployeeAttendanceRecord.objects.filter(
            user=user,
            date=date,
            checked_in_at__isnull=False,
        ).exists()

        if already_recorded:
            skipped_count += 1
            logger.debug(
                f"[AUTO_ATTENDANCE] User {user.id} already has attendance for {date}. Skipping."
            )
            continue

        # Gather all photos for this user on this date across all their activities
        all_activities_today = SalesDailyActivity.objects.filter(
            user=user,
            activity_date=date,
        ).prefetch_related('photos')

        all_photos = []
        for act in all_activities_today:
            all_photos.extend(list(act.photos.all().order_by('captured_at')))

        if not all_photos:
            skipped_count += 1
            logger.debug(
                f"[AUTO_ATTENDANCE] No photos found for user {user.id} on {date}. Cannot auto-mark."
            )
            continue

        # Prefer start_selfie for check-in
        start_photo = next(
            (p for p in all_photos if p.photo_type == 'start_selfie'), all_photos[0]
        )
        # Prefer end_selfie for check-out
        end_photo = next(
            (p for p in reversed(all_photos) if p.photo_type == 'end_selfie'),
            all_photos[-1],
        )

        checkin_time = start_photo.captured_at
        checkout_time = end_photo.captured_at if end_photo != start_photo else None
        checkin_lat = start_photo.latitude
        checkin_lon = start_photo.longitude

        # Determine branch
        bid = get_user_branch_id(user) or getattr(user, 'branch_id', None)
        if not bid:
            try:
                first_branch = (
                    Branch.objects.filter(organization=user.organization).first()
                    or Branch.objects.first()
                )
                bid = first_branch.id if first_branch else None
            except Exception:
                bid = None

        if not bid:
            logger.warning(
                f"[AUTO_ATTENDANCE] No branch found for user {user.id}. Cannot auto-mark attendance."
            )
            skipped_count += 1
            continue

        # Remove any existing 'absent' stale record
        EmployeeAttendanceRecord.objects.filter(
            user=user, date=date, status='absent'
        ).delete()

        # Calculate shortfall
        shortfall = 0
        exempt_roles = {'faculty', 'sweeper', 'maid', 'driver'}
        role = getattr(user, 'role', '')
        if role not in exempt_roles and checkin_time and checkout_time:
            duration_mins = int((checkout_time - checkin_time).total_seconds() / 60)
            shortfall = max(0, 540 - duration_mins)

        attendance_status = 'present' if checkout_time else 'checkout_pending'

        try:
            rec = EmployeeAttendanceRecord.objects.create(
                user=user,
                branch_id=bid,
                date=date,
                status=attendance_status,
                checked_in_at=checkin_time,
                checked_out_at=checkout_time,
                latitude=checkin_lat,
                longitude=checkin_lon,
                location_verified=False,
                shortfall_minutes=shortfall,
                marked_by=user,
            )
            marked_count += 1
            logger.info(
                f"[AUTO_ATTENDANCE] Auto-marked attendance for user {user.id} ({user.name or user.email}) "
                f"on {date}: check-in {checkin_time}, check-out {checkout_time}, "
                f"status={attendance_status}, shortfall={shortfall} min."
            )
        except Exception as e:
            logger.error(
                f"[AUTO_ATTENDANCE] Failed to create attendance for user {user.id} on {date}: {e}",
                exc_info=True,
            )
            skipped_count += 1

    logger.info(
        f"[AUTO_ATTENDANCE] Completed for {date}: "
        f"marked={marked_count}, skipped={skipped_count}."
    )
    return {
        'date': str(date),
        'marked': marked_count,
        'skipped': skipped_count,
    }
