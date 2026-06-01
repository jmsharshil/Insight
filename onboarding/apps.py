from django.apps import AppConfig


class OnboardingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'onboarding'

    def ready(self):
        import onboarding.signals  # noqa: F401
