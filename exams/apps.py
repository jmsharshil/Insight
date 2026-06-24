from django.apps import AppConfig


class ExamsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'exams'

    def ready(self):
        """Import signals so receivers are registered on app startup."""
        import exams.signals  # noqa: F401
