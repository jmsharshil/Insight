# scheduler/views.py

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from django.utils import timezone

from .models import ScheduledTask
from .services import TaskScheduler


class TaskCancelView(APIView):
    """
    Cancel a pending scheduled task.
    """
    def post(self, request, task_id):
        task = get_object_or_404(ScheduledTask, id=task_id)
        
        if task.status != "pending":
            return Response(
                {"detail": f"Task cannot be cancelled because it is {task.status}."},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        task.status = "cancelled"
        task.updated_at = timezone.now()
        task.save(update_fields=["status", "updated_at"])
        
        return Response({"detail": "Task cancelled successfully."})


class TaskRestartView(APIView):
    """
    Restart a failed, cancelled, completed, or even pending task immediately.
    """
    def post(self, request, task_id):
        task = get_object_or_404(ScheduledTask, id=task_id)
        
        if task.status == "running":
            return Response(
                {"detail": "Task is currently running and cannot be restarted."},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        task.status = "pending"
        task.retry_count = 0
        task.scheduled_at = timezone.now()
        task.started_at = None
        task.completed_at = None
        task.error_message = None
        task.save()
        
        # Enqueue it immediately
        TaskScheduler._schedule_in_memory(task.id, delay_seconds=0)
        
        return Response({"detail": "Task restarted successfully."})
