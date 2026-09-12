# leads/tasks.py

import logging
from datetime import timedelta
from django.utils import timezone
from .models import SalesDailyPlan
from chat.notifications import send_system_notification, send_whatsapp_with_fallback

logger = logging.getLogger(__name__)


def send_sales_plan_reminders():
    """
    Daily background task (scheduled to run at 8:00 AM IST).
    Sends WhatsApp and in-app system notifications to salespeople:
      1. 1 day before an event (for tomorrow's plans).
      2. The day of the event (for today's plans).
    """
    today = timezone.localdate()
    tomorrow = today + timedelta(days=1)

    tomorrow_count = 0
    today_count = 0

    # ── 1. Reminders 1 day before the event ──────────────────────────────────
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

    # ── 2. Reminders on the day of the event ─────────────────────────────────
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
        f"[SALES REMINDERS] Sent {tomorrow_count} 1-day-before and {today_count} day-of-event reminders."
    )
    return {
        'tomorrow_reminders': tomorrow_count,
        'today_reminders': today_count,
    }
