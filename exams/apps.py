from django.apps import AppConfig


class ExamsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'exams'

    def ready(self):
        """Import signals so receivers are registered on app startup."""
        import exams.signals  # noqa: F401
        
        try:
            from scheduler.services import TaskScheduler
            from exams.services import exam_reminders_task
            
            TaskScheduler.register('exam_reminders', exam_reminders_task)
            TaskScheduler.schedule(
                task_type='exam_reminders',
                delay_seconds=0,
                is_recurring=True,
                interval_seconds=900  # every 15 mins
            )
        except Exception:
            pass
