from django.apps import AppConfig


class LeadsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'leads'

    def ready(self):
        import leads.signals  # noqa: F401
        
        try:
            from scheduler.services import TaskScheduler
            from leads.services import lead_followup_reminders_task
            
            TaskScheduler.register('lead_followup_reminders', lead_followup_reminders_task)
            
            TaskScheduler.schedule(
                task_type='lead_followup_reminders',
                delay_seconds=0,
                is_recurring=True,
                interval_seconds=3600
            )
        except Exception:
            pass
