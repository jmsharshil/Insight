"""
students/signals.py
Post-save signal for Student (E1).

Fires auto_assign_batch() and create_student_fee() whenever a new Student
is created (i.e., admission → enrolled). Errors are caught and logged so
a single failing step never prevents enrollment from completing.
"""
import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from students.models import Student

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Student)
def on_student_created(sender, instance, created, **kwargs):
    """
    (Deprecated) Trigger batch assignment and fee creation on first student creation.
    These are now called explicitly at the end of StudentService.create_from_admission
    to ensure ParentLinks and other related objects exist beforehand.
    """
    pass
