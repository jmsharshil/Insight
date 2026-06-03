# This ensures the Celery app is loaded when Django starts,
# so that @shared_task decorators use it.
# Celery is disabled in this deployment.
# from .celery import app as celery_app
celery_app = None

__all__ = ('celery_app',)
