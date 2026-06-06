import logging
import re

from django.db import transaction

from auth_user.models import User
from auth_user.utils import (
    generate_temporary_password,
    send_student_login_credentials,
    send_parent_login_credentials,
)
from .models import Admission, AdmissionStatusHistory

logger = logging.getLogger(__name__)


class AdmissionService:

    # ── Counsellor Assignment ─────────────────────────────────────

    @staticmethod
    def get_next_counsellor():
        counsellors = list(
            User.objects.filter(role='counsellor', is_active=True).order_by('id')
        )

        if not counsellors:
            logger.warning("No active counsellors found for auto-assignment.")
            return None

        if len(counsellors) == 1:
            return counsellors[0]

        # Find the last assigned counsellor from the most recent admission
        last_admission = (
            Admission.objects
            .filter(assigned_counsellor__isnull=False)
            .order_by('-submitted_at')
            .values_list('assigned_counsellor_id', flat=True)
            .first()
        )

        if last_admission is None:
            # No previous assignment — start with the first counsellor
            return counsellors[0]

        # Find the index of the last assigned counsellor
        counsellor_ids = [c.id for c in counsellors]
        try:
            last_index = counsellor_ids.index(last_admission)
            # Rotate to the next counsellor
            next_index = (last_index + 1) % len(counsellors)
        except ValueError:
            # Last assigned counsellor no longer active/exists — start from first
            next_index = 0

        return counsellors[next_index]

    # ── Create Admission ──────────────────────────────────────────────────────

    @staticmethod
    @transaction.atomic
    def create_admission(validated_data: dict, user=None) -> Admission:
        """
        Creates an Admission record with status='approval_pending'.
        Auto-assigns a counsellor via round-robin if none is provided.
        No login credentials are created at this stage —
        credentials are only issued when the counsellor sets status to 'enrolled'.
        """
        lead_id = validated_data.pop('lead_id', None)
        lead = None

        if lead_id:
            from leads.models import Lead
            lead = Lead.objects.filter(id=lead_id).first()

        # Build document fields separately (FileField objects)
        DOC_FIELDS = [
            'doc_signature', 'doc_photo', 'doc_dob_certificate', 'doc_id_card',
            'doc_twelfth_receipt', 'doc_twelfth_marksheet', 'doc_category_cert',
        ]
        doc_data = {k: validated_data.pop(k) for k in DOC_FIELDS if k in validated_data}

        # Auto-assign counsellor if not already provided
        if 'assigned_counsellor' not in validated_data or validated_data.get('assigned_counsellor') is None:
            validated_data['assigned_counsellor'] = AdmissionService.get_next_counsellor()

        admission = Admission(lead=lead, **validated_data)

        # Save once to get a PK (needed for the upload path)
        admission.save()

        # Attach documents now that we have an ID
        for field, file in doc_data.items():
            setattr(admission, field, file)
        admission.save()

        # Record initial status history
        counsellor_name = (
            admission.assigned_counsellor.name
            if admission.assigned_counsellor else 'Unassigned'
        )
        AdmissionStatusHistory.objects.create(
            admission=admission,
            status=admission.status,
            changed_by=user,
            note=f'Admission submitted — assigned to {counsellor_name} for review.',
        )

        return admission

    # ── Update Admission Status ───────────────────────────────────────────────

    @staticmethod
    @transaction.atomic
    def update_status(admission: Admission, new_status: str, note: str = '', user=None):
        """
        Updates admission status. When status changes to 'enrolled',
        automatically creates student + parent login accounts and sends credentials.
        """
        old_status = admission.status

        admission.status = new_status
        admission.note = note
        admission.save(update_fields=['status', 'note', 'updated_at'])

        AdmissionStatusHistory.objects.create(
            admission=admission,
            status=new_status,
            changed_by=user,
            note=note,
        )

        # Trigger credential creation only on transition to 'enrolled'
        if new_status == 'enrolled' and old_status != 'enrolled':
            try:
                AdmissionService._create_user_accounts(admission)
                logger.info(
                    f"Student enrolled — credentials created for admission {admission.id}"
                )
            except Exception as e:
                logger.error(
                    f"Failed to create user accounts for admission {admission.id}: {e}"
                )
                # Don't re-raise — status is already saved

        return admission

    # ── Create Student + Parent Accounts (called only on enrollment) ─────────

    @staticmethod
    def _create_user_accounts(admission: Admission):
        student_name = f"{admission.first_name} {admission.surname}".strip()

        student_user, student_password = AdmissionService._create_or_update_user(
            email=admission.email,
            phone=re.sub(r'\D', '', admission.phone_student),
            name=student_name,
            role='student',
            linked_student=None,
        )

        parent_phone = re.sub(r'\D', '', admission.phone_father or admission.phone_father_2)
        parent_name  = admission.father_name.strip() or f"Parent of {student_name}"

        parent_user, parent_password = AdmissionService._create_or_update_user(
            email=admission.email_parent,
            phone=parent_phone,
            name=parent_name,
            role='parents',
            linked_student=student_user,
        )

        try:
            send_student_login_credentials(student_user, student_password)
            send_parent_login_credentials(parent_user, student_user, parent_password)
            logger.info(
                f"Credentials sent for admission {admission.id} "
                f"(student={student_user.email}, parent={parent_user.email})"
            )
        except Exception as e:
            logger.error(
                f"Email sending failed for admission {admission.id}: {e}"
            )
            # Don't raise — accounts are created even if email fails

    # ── User Create / Update Helper ───────────────────────────────────────────

    @staticmethod
    def _build_unique_username(email: str) -> str:
        base = email.split('@')[0].strip() or 'student'
        username = base
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f"{base}{counter}"
            counter += 1
        return username

    @staticmethod
    def _create_or_update_user(*, email, phone, name, role, linked_student=None):
        if not email:
            raise ValueError("Email is required to create login credentials.")
        if not phone:
            raise ValueError("Phone is required to create login credentials.")

        password = generate_temporary_password()
        user = User.objects.filter(email=email).first()

        if user:
            if not user.username:
                user.username = AdmissionService._build_unique_username(email)
            user.phone          = phone
            user.name           = name or user.name
            user.role           = role
            user.is_active      = True
            user.linked_student = linked_student
            user.set_password(password)
            user.save()
        else:
            user = User.objects.create_user(
                username=AdmissionService._build_unique_username(email),
                email=email,
                password=password,
                role=role,
                phone=phone,
                name=name,
                is_active=True,
                linked_student=linked_student,
            )

        return user, password