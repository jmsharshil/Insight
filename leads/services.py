import logging
from django.utils import timezone
from datetime import timedelta
from .models import Lead
from chat.notifications import send_system_notification

logger = logging.getLogger(__name__)

def lead_followup_reminders_task(*args, **kwargs):
    """
    Background task to send reminders for lead follow-ups and visits.
    Runs every hour.
    """
    now = timezone.now()
    one_day_from_now = now + timedelta(days=1)
    two_hours_from_now = now + timedelta(hours=2)
    today = now.date()

    # Get leads in follow_up or visit stage
    active_leads = Lead.objects.filter(
        current_stage__in=['follow_up', 'visit']
    ).select_related('assigned_to')

    for lead in active_leads:
        target_date = None
        event_name = ""
        
        if lead.current_stage == 'follow_up' and lead.followup_date:
            target_date = lead.followup_date
            event_name = "Follow-up"
        elif lead.current_stage == 'visit' and lead.visit_date:
            target_date = lead.visit_date
            event_name = "Visit"
            
        if not target_date:
            continue
            
        user_to_notify = lead.assigned_to

        if not user_to_notify:
            continue
            
        updated = False

        # 1-day reminder
        if target_date <= one_day_from_now and target_date > now and not lead.reminder_1d_sent:
            send_system_notification(
                user_id=str(user_to_notify.id),
                title=f'{event_name} Reminder: Tomorrow',
                body=f"Reminder: {event_name} for lead {lead.first_name} {lead.surname} is scheduled for tomorrow at {timezone.localtime(target_date).strftime('%I:%M %p')}.",
                metadata={'lead_id': str(lead.id)}
            )
            lead.reminder_1d_sent = True
            updated = True
            
        # 2-hour reminder
        if target_date <= two_hours_from_now and target_date > now and not lead.reminder_2h_sent:
            send_system_notification(
                user_id=str(user_to_notify.id),
                title=f'{event_name} Reminder: In 2 Hours',
                body=f"Reminder: {event_name} for lead {lead.first_name} {lead.surname} is scheduled in 2 hours.",
                metadata={'lead_id': str(lead.id)}
            )
            lead.reminder_2h_sent = True
            updated = True
            
        # Overdue daily reminder (if target_date is in the past and stage hasn't changed)
        if target_date < now:
            if lead.last_overdue_reminder_sent != today:
                send_system_notification(
                    user_id=str(user_to_notify.id),
                    title=f'Overdue {event_name} Reminder',
                    body=f"The {event_name.lower()} for lead {lead.first_name} {lead.surname} was scheduled for {timezone.localtime(target_date).strftime('%Y-%m-%d %I:%M %p')} and is now overdue. Please update the status.",
                    metadata={'lead_id': str(lead.id)}
                )
                lead.last_overdue_reminder_sent = today
                updated = True
                
        if updated:
            lead.save(update_fields=['reminder_1d_sent', 'reminder_2h_sent', 'last_overdue_reminder_sent'])
