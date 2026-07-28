# """
# leads/signals.py — Cross-module signals for CRM → Admissions pipeline.

# Fires when a Lead's status is updated to 'converted', triggering
# automatic Admission record creation in the onboarding app.
# """

import logging
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model

logger = logging.getLogger(__name__)


@receiver(pre_save, sender='leads.Lead')
def auto_assign_lead(sender, instance, **kwargs):
    """
    Automatically assign new leads using round-robin logic.
    - contact form -> tele_caller
    - inquiry form -> counsellor
    Does not override if assigned_to is already set.
    """
    if instance.id is None and instance.assigned_to is None:
        role_to_assign = None
        if instance.form_type == 'contact':
            role_to_assign = 'tele_caller'
        elif instance.form_type == 'inquiry':
            role_to_assign = 'counsellor'
        
        if role_to_assign:
            User = get_user_model()
            # Fetch active users of the required role, order by ID for consistent round-robin
            users = User.objects.filter(role=role_to_assign, is_active=True).order_by('id')
            
            if users.exists():
                users_list = list(users)
                # Find the most recently created lead that was assigned to this role for this form type
                last_lead = sender.objects.filter(
                    form_type=instance.form_type,
                    assigned_to__role=role_to_assign
                ).order_by('-created_at').first()
                
                if last_lead and last_lead.assigned_to:
                    try:
                        last_idx = users_list.index(last_lead.assigned_to)
                        next_idx = (last_idx + 1) % len(users_list)
                        instance.assigned_to = users_list[next_idx]
                    except ValueError:
                        # Fallback if the previous assignee is no longer in the active users list
                        instance.assigned_to = users_list[0]
                else:
                    # No previous leads, start with the first user
                    instance.assigned_to = users_list[0]


# @receiver(post_save, sender='leads.Lead')
# def lead_status_changed(sender, instance, created, **kwargs):
#     """
#     When a Lead's status changes to 'converted', auto-create an
#     Admission record in the onboarding app if one doesn't already exist.
#     """
#     if created:
#         return  # Only trigger on updates, not creation
# 
#     if instance.current_stage != 'converted':
#         return
# 
#     try:
#         from onboarding.models import Admission
# 
#         # Avoid duplicate admission
#         if Admission.objects.filter(lead=instance).exists():
#             logger.info(f"Admission already exists for Lead {instance.id}")
#             return
# 
#         admission = Admission.objects.create(
#             lead=instance,
#             branch=instance.branch,
#             student_name=instance.student_name,
#             student_email=instance.email,
#             student_phone=instance.phone,
#             course=instance.course,
#             status='approval_pending',
#         )
#         logger.info(f"Auto-created Admission {admission.id} from Lead {instance.id}")
# 
#     except Exception as e:
#         logger.error(f"Failed to auto-create Admission from Lead {instance.id}: {e}")
