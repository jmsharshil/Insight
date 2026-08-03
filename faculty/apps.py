from django.apps import AppConfig


class FacultyConfig(AppConfig):
    name = 'faculty'

    def ready(self):
        import faculty.signals  # noqa: F401
