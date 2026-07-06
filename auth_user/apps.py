from django.apps import AppConfig


class AuthUserConfig(AppConfig):
    name = 'auth_user'
    _retention_started = False

    def ready(self):
        import auth_user.signals  # noqa: F401

        if AuthUserConfig._retention_started:
            return
        AuthUserConfig._retention_started = True

        import os
        import sys

        if any(cmd in sys.argv for cmd in ('test', 'migrate', 'makemigrations', 'collectstatic')):
            return

        is_main_process = (
            os.environ.get('RUN_MAIN') == 'true' or
            os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or
            not os.environ.get('GUNICORN_CMD_ARGS')
        )

        if is_main_process:
            from .tasks import schedule_notification_retention
            schedule_notification_retention()
