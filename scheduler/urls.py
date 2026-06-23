# scheduler/urls.py

from django.urls import path
from .views import TaskCancelView, TaskRestartView

app_name = "scheduler"

urlpatterns = [
    path('tasks/<uuid:task_id>/cancel/', TaskCancelView.as_view(), name='task-cancel'),
    path('tasks/<uuid:task_id>/restart/', TaskRestartView.as_view(), name='task-restart'),
]
