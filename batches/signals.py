# ═══════════════════════════════════════════════════════════════════════════════
#  Signals for auto-updating Subject.total_hours based on Chapter.duration_hours
# ═══════════════════════════════════════════════════════════════════════════════
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import Chapter, Subject
@receiver(post_save, sender=Chapter)
def update_subject_total_hours(sender, instance, created=False, **kwargs):
    """Update subject's total_hours whenever a chapter is saved (created/updated)."""
    if instance.subject:
        instance.subject.update_total_hours()


@receiver(post_delete, sender=Chapter)
def update_subject_total_hours_on_delete(sender, instance, **kwargs):
    """Update subject's total_hours when a chapter is deleted."""
    if instance.subject and instance.subject.pk:
        # Refresh the subject instance from DB in case it was deleted (though unlikely)
        try:
            subject = Subject.objects.get(pk=instance.subject.pk)
            subject.update_total_hours()
        except Subject.DoesNotExist:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
#  Signals for auto-creating ChatRoom when a Batch is created,
#  and syncing participants when BatchStudent / BatchFaculty are changed.
# ═══════════════════════════════════════════════════════════════════════════════
import logging
from .models import Batch, BatchStudent, BatchFaculty

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Batch)
def auto_create_batch_chat_room(sender, instance, created, **kwargs):
    """Create a group ChatRoom for every newly created Batch."""
    if not created:
        return
    if instance.chat_room_id:
        return  # already linked (e.g. manual creation)
    try:
        from chat.models import ChatRoom
        room = ChatRoom.objects.create(
            name=f"{instance.batch_code} — {instance.name}",
            room_type='group',
        )
        
        # Auto-add admin roles to the batch chat room
        from django.contrib.auth import get_user_model
        from django.db.models import Q
        User = get_user_model()
        admins_qs = User.objects.filter(
            role__in=['super_admin', 'admin_senior_executive', 'branch_manager'], 
            is_active=True
        )
        if instance.branch_id:
            admins_qs = admins_qs.filter(Q(branch_id=instance.branch_id) | Q(role='super_admin'))
        elif instance.organization_id:
            admins_qs = admins_qs.filter(Q(organization_id=instance.organization_id) | Q(role='super_admin'))
        
        admins = list(admins_qs)
        if admins:
            room.participants.add(*admins)

        # Use update to avoid triggering post_save again
        Batch.objects.filter(pk=instance.pk).update(chat_room=room)
        instance.chat_room_id = room.id
        instance.chat_room = room
        logger.info(f"Auto-created ChatRoom {room.id} for Batch {instance.batch_code}")
    except Exception as e:
        logger.error(f"Failed to auto-create ChatRoom for Batch {instance.batch_code}: {e}")


@receiver(post_save, sender=BatchStudent)
def add_student_to_batch_chat(sender, instance, created, **kwargs):
    """When a student is enrolled in a batch, add them to the batch ChatRoom."""
    if not created:
        return
    try:
        batch = instance.batch
        if not batch.chat_room_id:
            return
        user = instance.student.user
        if user:
            batch.chat_room.participants.add(user)
            logger.info(f"Added student user {user.id} to ChatRoom for Batch {batch.batch_code}")
            
        # Add parents to the chat room
        parents = [link.parent for link in instance.student.parent_links.select_related('parent').all() if link.parent]
        if parents:
            batch.chat_room.participants.add(*parents)
            logger.info(f"Added {len(parents)} parent(s) to ChatRoom for Batch {batch.batch_code}")
    except Exception as e:
        logger.error(f"Failed to add student to batch chat: {e}")


@receiver(post_delete, sender=BatchStudent)
def remove_student_from_batch_chat(sender, instance, **kwargs):
    """When a student is removed from a batch, remove them from the batch ChatRoom."""
    try:
        batch = instance.batch
        if not batch.chat_room_id:
            return
        user = instance.student.user
        if user:
            batch.chat_room.participants.remove(user)
            logger.info(f"Removed student user {user.id} from ChatRoom for Batch {batch.batch_code}")
            
        # Remove parents from the chat room
        parents = [link.parent for link in instance.student.parent_links.select_related('parent').all() if link.parent]
        if parents:
            batch.chat_room.participants.remove(*parents)
            logger.info(f"Removed {len(parents)} parent(s) from ChatRoom for Batch {batch.batch_code}")
    except Exception as e:
        logger.error(f"Failed to remove student from batch chat: {e}")


@receiver(post_save, sender=BatchFaculty)
def add_faculty_to_batch_chat(sender, instance, created, **kwargs):
    """When a faculty is assigned to a batch, add them to the batch ChatRoom."""
    if not created:
        return
    try:
        batch = instance.batch
        if not batch.chat_room_id:
            return
        user = instance.faculty.user
        if user:
            batch.chat_room.participants.add(user)
            logger.info(f"Added faculty user {user.id} to ChatRoom for Batch {batch.batch_code}")
    except Exception as e:
        logger.error(f"Failed to add faculty to batch chat: {e}")


@receiver(post_delete, sender=BatchFaculty)
def remove_faculty_from_batch_chat(sender, instance, **kwargs):
    """When a faculty is removed from a batch, remove them from the batch ChatRoom."""
    try:
        batch = instance.batch
        if not batch.chat_room_id:
            return
        user = instance.faculty.user
        if user:
            batch.chat_room.participants.remove(user)
            logger.info(f"Removed faculty user {user.id} from ChatRoom for Batch {batch.batch_code}")
    except Exception as e:
        logger.error(f"Failed to remove faculty from batch chat: {e}")
