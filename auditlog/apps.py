from django.apps import AppConfig


class AuditlogConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'auditlog'
    _flush_started = False  # Class-level flag to prevent duplicate starts

    def ready(self):
        import auditlog.signals  # noqa: F401

        # Start the background periodic flush to blob storage
        import os
        import sys

        # Prevent during tests
        if 'test' in sys.argv:
            return

        # Prevent duplicate starts
        if AuditlogConfig._flush_started:
            return
        AuditlogConfig._flush_started = True

        # Start flush task in all environments (local dev, Gunicorn, Azure)
        # Only in the main process to avoid double execution
        is_main_process = (
            os.environ.get('RUN_MAIN') == 'true' or  # Django dev server
            os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or  # Werkzeug dev server
            not os.environ.get('GUNICORN_CMD_ARGS')  # Not Gunicorn worker
        )

        # if is_main_process:
            # from .tasks import schedule_periodic_flush
            # schedule_periodic_flush()
