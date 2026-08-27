"""
onboarding/signals.py

NOTE: Student profile creation is handled explicitly by StudentService.create_from_admission()
called inside AdmissionApproveView (onboarding/views.py).

This signal file is intentionally left as a no-op to avoid duplicate creation conflicts.
Do NOT add post_save logic here for Student creation — use the service layer instead.
"""

import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Admission

logger = logging.getLogger(__name__)

@receiver(post_save, sender=Admission)
def sync_documents_to_student(sender, instance, **kwargs):
    """
    When Admission documents are updated, sync them to the corresponding Student
    profile if it has already been created.
    """
    try:
        if not hasattr(instance, 'student_profile'):
            return
        
        student = getattr(instance, 'student_profile', None)
        if not student:
            return

        doc_mapping = {
            'doc_signature': 'doc_signature',
            'doc_photo': 'photo',
            'doc_dob_certificate': 'doc_dob_certificate',
            'doc_id_card': 'doc_id_proof',
            'doc_twelfth_marksheet': 'doc_twelfth_marksheet',
            'doc_category_cert': 'doc_category_cert',
        }

        update_fields = []
        for adm_field, std_field in doc_mapping.items():
            adm_file = getattr(instance, adm_field, None)
            std_file = getattr(student, std_field, None)
            
            adm_name = adm_file.name if adm_file else None
            std_name = std_file.name if std_file else None

            if adm_name != std_name:
                setattr(student, std_field, adm_file)
                update_fields.append(std_field)

        if update_fields:
            if 'updated_at' not in update_fields:
                update_fields.append('updated_at')
            student.save(update_fields=update_fields)
            logger.info(f"Synced updated documents {update_fields} from Admission {instance.id} to Student {student.admission_number}")
            
            # Regenerate ID card if photo was updated
            if 'photo' in update_fields and getattr(student, 'photo', None):
                from students.utils import StudentService
                try:
                    StudentService.generate_id_card(student)
                    logger.info(f"Regenerated ID card for Student {student.admission_number} after photo update.")
                except Exception as e:
                    logger.error(f"Failed to regenerate ID card after photo sync: {e}")
            
    except Exception as e:
        logger.error(f"Error syncing documents from Admission {instance.id} to Student: {e}", exc_info=True)
