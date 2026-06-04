"""
Celery configuration for Insight Institute ERP.

Autodiscovers tasks in all installed apps.
Falls back gracefully if Redis/broker is unavailable.
"""

# import os
# from celery import Celery

# os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'insight.settings')

# app = Celery('insight')

# # Read config from Django settings, prefixed with CELERY_
# app.config_from_object('django.conf:settings', namespace='CELERY')

# # Autodiscover tasks.py in all installed apps
# app.autodiscover_tasks()


# @app.task(bind=True, ignore_result=True)
# def debug_task(self):
#     """Diagnostic task to verify Celery is working."""
#     print(f'Request: {self.request!r}')
