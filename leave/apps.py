from django.apps import AppConfig


class LeaveConfig(AppConfig):
    name = 'leave'

    def ready(self):
        import leave.signals
