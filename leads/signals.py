# """
# leads/signals.py — Cross-module signals for CRM → Admissions pipeline.

# Fires when a Lead's status is updated to 'converted', triggering
# automatic Admission record creation in the onboarding app.
# """

import logging
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model

logger = logging.getLogger(__name__)


def _clear_affected_dashboard_caches(instance):
    """Invalidate sales dashboards after lead counts or assignments change."""
    from dashboard.services import clear_dashboard_cache

    User = get_user_model()
    users = User.objects.filter(is_active=True)
    if getattr(instance, 'branch_id', None):
        users = users.filter(branch_id=instance.branch_id)
    elif getattr(instance, 'branch', None) and getattr(instance.branch, 'organization_id', None):
        users = users.filter(organization_id=instance.branch.organization_id)

    try:
        affected_users = users.filter(role__in={
            'sales_senior_executive', 'sales_executive', 'counsellor',
            'tele_caller', 'front_desk',
        })
        for user in affected_users:
            clear_dashboard_cache(user)
    except Exception as exc:
        logger.warning("Failed to clear lead dashboard cache: %s", exc)


@receiver(pre_save, sender='leads.Lead')
def auto_assign_lead(sender, instance, **kwargs):
    """
    Automatically assign new leads:
    - Telecaller leads (contact form) are auto-assigned via round-robin,
      considering ONLY active users with primary role as 'tele_caller'.
    - Counsellor leads (inquiry form / others) are NOT auto-assigned;
      they remain unassigned so Front Desk can assign them manually.
    Does not override if assigned_to is already set.
    """
    if instance.id is None and instance.assigned_to is None:
        # Only contact form leads (telecaller leads) are auto-assigned
        if instance.form_type == 'contact':
            User = get_user_model()
            # Telecaller leads: consider only users with PRIMARY role as tele_caller
            users = User.objects.filter(role='tele_caller', is_active=True)

            if instance.branch:
                branch_telecallers = users.filter(branch=instance.branch)
                if branch_telecallers.exists():
                    users = branch_telecallers
                elif getattr(instance.branch, 'organization', None):
                    org_telecallers = users.filter(organization=instance.branch.organization)
                    if org_telecallers.exists():
                        users = org_telecallers

            users_list = list(users.order_by('id'))
            if users_list:
                # Find the most recently created contact lead that was assigned to a primary tele_caller
                last_lead = sender.objects.filter(
                    assigned_to__role='tele_caller',
                    form_type='contact',
                ).order_by('-created_at').first()
                
                if last_lead and last_lead.assigned_to and last_lead.assigned_to in users_list:
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


@receiver(post_save, sender='leads.Lead')
def notify_new_lead_assignment(sender, instance, created, **kwargs):
    """
    Notify the assignee when a new lead is created and assigned to them (e.g. via auto-assignment or public form).
    """
    if created and instance.assigned_to:
        from chat.notifications import send_system_notification
        title = "New Lead Assigned"
        body = f"You have been assigned a new lead: {instance.first_name} {instance.surname}".strip()
        try:
            send_system_notification(
                user_id=str(instance.assigned_to.id),
                title=title,
                body=body,
                metadata={
                    "type": "lead_assigned",
                    "lead_id": str(instance.id)
                }
            )
        except Exception as e:
            logger.error(f"Failed to notify user {instance.assigned_to.id} for new lead {instance.id}: {e}")


@receiver(post_save, sender='leads.Lead')
def clear_lead_dashboard_cache(sender, instance, **kwargs):
    _clear_affected_dashboard_caches(instance)


@receiver(post_delete, sender='leads.Lead')
def clear_deleted_lead_dashboard_cache(sender, instance, **kwargs):
    _clear_affected_dashboard_caches(instance)

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
