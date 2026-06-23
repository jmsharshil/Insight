from django.apps import AppConfig


class AuthUserConfig(AppConfig):
    name = 'auth_user'

    def ready(self):
        import auth_user.signals  # noqa: F401
