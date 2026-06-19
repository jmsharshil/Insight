from django.apps import AppConfig


class BatchesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'batches'

    def ready(self):
        # Import signals to register receivers for auto-updating Subject.total_hours
        # This ensures signals are connected when the app is ready
        import batches.signals  # noqa: F401
        # The @receiver decorators in models.py will register the Chapter signals
