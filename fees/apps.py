from django.apps import AppConfig


class FeesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'fees'

    def ready(self):
        import fees.signals  # noqa: F401

        try:
            from scheduler.services import TaskScheduler
            from fees.services import payment_approval_reminders_task
            
            TaskScheduler.register('payment_approval_reminders', payment_approval_reminders_task)
            
            TaskScheduler.schedule(
                task_type='payment_approval_reminders',
                delay_seconds=0,
                is_recurring=True,
                interval_seconds=7200
            )
        except Exception:
            pass
