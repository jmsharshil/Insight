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

    # ── Create Admission ──────────────────────────────────────────────────────

    @staticmethod
    @transaction.atomic
    def create_admission(validated_data: dict, user=None) -> Admission:
        """
        Creates an Admission record, then immediately creates
        student + parent login accounts and sends credentials.
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

        admission = Admission(lead=lead, **validated_data)

        # Save once to get a PK (needed for the upload path)
        admission.save()

        # Attach documents now that we have an ID
        for field, file in doc_data.items():
            setattr(admission, field, file)
        admission.save()

        # Record initial status history
        AdmissionStatusHistory.objects.create(
            admission=admission,
            status=admission.status,
            changed_by=user,
            note='Admission submitted.',
        )

        # Create student + parent login accounts
        try:
            AdmissionService._create_user_accounts(admission)
        except Exception as e:
            # Log but don't roll back — admission data is already saved
            logger.error(
                f"Failed to create user accounts for admission {admission.id}: {e}"
            )

        return admission

    # ── Create Student + Parent Accounts ─────────────────────────────────────

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
            if User.objects.filter(phone=phone).exclude(id=user.id).exists():
                raise ValueError(f"Phone {phone} is already used by another account.")
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
            if User.objects.filter(phone=phone).exists():
                raise ValueError(f"Phone {phone} is already used by another account.")
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

    # ── Update Admission Status ───────────────────────────────────────────────

    @staticmethod
    @transaction.atomic
    def update_status(admission: Admission, new_status: str, note: str = '', user=None):
        admission.status = new_status
        admission.save(update_fields=['status', 'updated_at'])

        AdmissionStatusHistory.objects.create(
            admission=admission,
            status=new_status,
            changed_by=user,
            note=note,
        )
        return admission