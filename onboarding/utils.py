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
        from core.utils import get_role_filter_q
        counsellors = list(
            User.objects.filter(get_role_filter_q('counsellor'), is_active=True).order_by('id')
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
        Creates an Admission record with status='form_pending'.
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

        from auth_user.utils import generate_username
        student_username, _ = generate_username(
            role='student',
            branch=admission.branch,
            course=admission.course,
            batch_attempt=admission.batch_attempt,
            attempt_year=admission.attempt_year
        )

        student_user, student_password = AdmissionService._create_or_update_user(
            email=admission.email,
            phone=re.sub(r'\D', '', admission.phone_student or ''),
            name=student_name,
            role='student',
            linked_student=None,
            organization=admission.branch.organization if admission.branch else None,
            branch=admission.branch,
            username=student_username,
        )
        student_user.branches.set([admission.branch]) if admission.branch else None

        try:
            if student_password:
                send_student_login_credentials(student_user, student_password)
                logger.info(f"Student credentials sent for admission {admission.id}")
        except Exception as e:
            logger.error(f"Student email sending failed for admission {admission.id}: {e}")

        # ── Parent User Account Creation ──────────────────────────────────────
        raw_father = admission.father_name.strip() if admission.father_name else ''
        raw_mother = admission.mother_name.strip() if admission.mother_name else ''
        parent_name = raw_father or raw_mother or f"Parent of {student_name}"

        # Safely determine parent phone (with fallbacks to student phone numbers)
        parent_phone = re.sub(
            r'\D', '',
            admission.phone_father or admission.phone_father_2 or admission.phone_student_2 or admission.phone_student or ''
        )

        # Safely determine parent email (fallback to student email if not separately provided)
        parent_email = (admission.email_parent or '').strip()
        if not parent_email:
            parent_email = (admission.email or '').strip()

        if parent_email and parent_phone:
            # Generate guaranteed-unique username for parent
            try:
                parent_username, _ = generate_username(
                    role='parents',
                    branch=admission.branch,
                    course=admission.course,
                    batch_attempt=admission.batch_attempt,
                    attempt_year=admission.attempt_year,
                )
            except Exception:
                parent_username = student_username.replace('_S_', '_P_', 1) if '_S_' in student_username else f"{student_username}_P"

            counter = 1
            base_p_username = parent_username
            while User.objects.filter(username=parent_username).exists():
                parent_username = f"{base_p_username}_{counter}"
                counter += 1

            parent_user, parent_password = AdmissionService._create_or_update_user(
                email=parent_email,
                phone=parent_phone,
                name=parent_name,
                role='parents',
                linked_student=student_user,
                organization=admission.branch.organization if admission.branch else None,
                branch=admission.branch,
                username=parent_username,
            )
            if admission.branch:
                parent_user.branches.set([admission.branch])

            # Ensure ParentLink is established if Student master profile exists
            if hasattr(admission, 'student_profile') and admission.student_profile:
                try:
                    from students.models import ParentLink
                    ParentLink.objects.get_or_create(
                        student=admission.student_profile,
                        parent=parent_user,
                        defaults={
                            'relationship': 'father' if raw_father else ('mother' if raw_mother else 'parent'),
                            'is_primary': True,
                        }
                    )
                except Exception as link_err:
                    logger.error(f"Error creating ParentLink for admission {admission.id}: {link_err}")

            try:
                if parent_password:
                    send_parent_login_credentials(parent_user, student_user, parent_password)
                    logger.info(f"Parent credentials sent for admission {admission.id}")
                else:
                    # Parent account already existed: re-send or notify with student link
                    send_parent_login_credentials(parent_user, student_user, "Use your existing password or reset if forgotten")
                    logger.info(f"Parent account already existed, added student link for admission {admission.id}.")
            except Exception as e:
                logger.error(f"Parent email sending failed for admission {admission.id}: {e}")
        else:
            logger.warning(f"Skipping parent account creation for admission {admission.id} (missing email and phone).")

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
    def _create_or_update_user(*, email, phone, name, role, linked_student=None, organization=None, branch=None, username=None):
        if not email:
            raise ValueError("Email is required to create login credentials.")
        if not phone:
            raise ValueError("Phone is required to create login credentials.")

        # Look up by username first, or by (email, role) so parent and student don't collide if sharing an email
        user = None
        if username:
            user = User.objects.filter(username=username).first()
        if not user and email:
            user = User.objects.filter(email__iexact=email, role=role).first()

        if user:
            if not user.username:
                user.username = username or AdmissionService._build_unique_username(email)
            user.phone          = phone
            user.name           = name or user.name
            user.role           = role
            user.is_active      = True
            if organization:
                user.organization = organization
            if branch:
                user.branch = branch
            user.save()
            if linked_student:
                user.linked_students.add(linked_student)
            return user, None
        else:
            password = generate_temporary_password()
            user = User.objects.create_user(
                username=username or AdmissionService._build_unique_username(email),
                email=email,
                password=password,
                role=role,
                phone=phone,
                name=name,
                is_active=True,
                organization=organization,
                branch=branch,
            )
            if linked_student:
                user.linked_students.add(linked_student)
            return user, password

import requests
from requests.auth import HTTPBasicAuth
from django.conf import settings

def create_razorpay_payment_link(amount, reference_id, customer_name, customer_email, customer_contact, description="Fee Payment"):
    url = "https://api.razorpay.com/v1/payment_links"
    payload = {
        "amount": int(amount * 100), # amount in paise
        "currency": "INR",
        "accept_partial": False,
        "reference_id": str(reference_id),
        "description": description,
        "customer": {
            "name": customer_name,
            "email": customer_email,
            "contact": customer_contact
        },
        "notify": {
            "sms": False,
            "email": False 
        },
        "reminder_enable": True,
    }
    
    # # Route payment to specific bank account via Razorpay Route (linked accounts)
    # if razorpay_account_id:
    #     payload["transfers"] = [
    #         {
    #             "account": razorpay_account_id,
    #             "amount": int(amount * 100),
    #             "currency": "INR",
    #             "on_hold": 0,
    #         }
    #     ]
    
    if hasattr(settings, 'RAZORPAY_KEY_ID') and settings.RAZORPAY_KEY_ID:
        try:
            response = requests.post(
                url,
                json=payload,
                auth=HTTPBasicAuth(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
            )
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Razorpay Payment Link error: {response.text}")
                return None
        except Exception as e:
            logger.error(f"Razorpay request exception: {e}")
            return None
    return None

def create_razorpay_refund(payment_id, amount, reason=""):
    url = f"https://api.razorpay.com/v1/payments/{payment_id}/refund"
    payload = {
        "amount": int(amount * 100),
        "notes": {
            "reason": reason
        }
    }
    if hasattr(settings, 'RAZORPAY_KEY_ID') and settings.RAZORPAY_KEY_ID:
        try:
            response = requests.post(
                url,
                json=payload,
                auth=HTTPBasicAuth(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
            )
            if response.status_code == 200:
                return response.json()
            else:
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Razorpay Refund error: {response.text}")
                return None
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Razorpay refund request exception: {e}")
            return None
    return None


def get_module_fee(fee_structure, group_module):
    """
    Resolves the fee component from the fee structure matching the student's group_module selection.
    Falls back to institute_fees_all_modules or total_amount if specific module fee is not set.
    """
    from decimal import Decimal
    if not fee_structure:
        return Decimal('0')

    gm = (group_module or '').strip().lower()
    if gm == 'module_1' and fee_structure.institute_fees_module_1:
        return Decimal(str(fee_structure.institute_fees_module_1))
    elif gm == 'module_2' and fee_structure.institute_fees_module_2:
        return Decimal(str(fee_structure.institute_fees_module_2))
    elif gm == 'module_3' and fee_structure.institute_fees_module_3:
        return Decimal(str(fee_structure.institute_fees_module_3))
    elif gm == 'module_4' and fee_structure.institute_fees_module_4:
        return Decimal(str(fee_structure.institute_fees_module_4))
    elif gm == 'module_5' and fee_structure.institute_fees_module_5:
        return Decimal(str(fee_structure.institute_fees_module_5))
    elif gm in ('all', 'both', 'full') and fee_structure.institute_fees_all_modules:
        return Decimal(str(fee_structure.institute_fees_all_modules))

    if fee_structure.institute_fees_all_modules:
        return Decimal(str(fee_structure.institute_fees_all_modules))
    return Decimal(str(fee_structure.total_amount or 0))


def sync_admission_payment(admission, request=None, force=False, new_payment=False):
    """
    Ensures that when payment details (screenshot, transaction_id, payment_amount, or offline payment choice)
    are submitted for an admission, a corresponding fees.Payment record is created or updated in 'approval_pending'
    status, and the admission status is synchronized.
    """
    from decimal import Decimal
    from django.utils import timezone
    from fees.models import Payment
    from .models import AdmissionStatusHistory

    # Determine payment mode
    pc = str(admission.payment_choice or '').strip().lower()
    if pc in ('cheque', 'check'):
        mapped_mode = 'cheque'
    elif pc == 'cash':
        mapped_mode = 'cash'
    else:
        mapped_mode = 'online'

    # Determine amount
    pay_amount = admission.payment_amount
    if not pay_amount or Decimal(str(pay_amount)) <= 0:
        if getattr(admission, 'fee_structure', None):
            fs = admission.fee_structure
            if admission.payment_type == 'token':
                pay_amount = Decimal(str(fs.token_amount or 0))
            elif admission.payment_type == 'full_payment':
                pay_amount = get_module_fee(fs, admission.group_module)
            else:
                pay_amount = Decimal(str(admission.total_fees or 0))
        else:
            pay_amount = Decimal(str(admission.total_fees or 0))

    if not pay_amount or Decimal(str(pay_amount)) <= 0:
        default_course_fees = {
            'cseet': Decimal('1000'),
            'cs_executive': Decimal('2000'),
            'cs_professional': Decimal('5000'),
        }
        pay_amount = default_course_fees.get(admission.course, Decimal('0'))

    # Has payment details?
    has_payment_data = bool(
        admission.payment_screenshot or
        admission.transaction_id or
        (admission.payment_amount and Decimal(str(admission.payment_amount)) > 0) or
        pc in ('cash', 'cheque')
    )

    if not has_payment_data and not force:
        return None

    # Find or create Payment
    payment = Payment.objects.filter(admission=admission).first()
    created = False
    if not payment:
        payment = Payment.objects.create(
            admission=admission,
            amount=pay_amount or Decimal('0'),
            payment_mode=mapped_mode,
            transaction_ref=admission.transaction_id or '',
            payment_proof=admission.payment_screenshot if admission.payment_screenshot else None,
            status='approval_pending',
            payment_date=timezone.now().date(),
            note=f"Payment submitted for admission #{admission.id}. Tx: {admission.transaction_id or 'N/A'}",
        )
        created = True
        logger.info(f"Created pending Payment {payment.receipt_number} for admission #{admission.id}")
    else:
        if payment.status in ('pending', 'approval_pending', 'level_1_approved'):
            if pay_amount and Decimal(str(pay_amount)) > 0:
                payment.amount = pay_amount
            payment.payment_mode = mapped_mode
            if admission.transaction_id:
                payment.transaction_ref = admission.transaction_id
            if admission.payment_screenshot:
                payment.payment_proof = admission.payment_screenshot
            if payment.status == 'pending':
                payment.status = 'approval_pending'
            payment.payment_date = timezone.now().date()
            payment.note = f"Payment updated for admission #{admission.id}. Tx: {admission.transaction_id or 'N/A'}"
            payment.save()
            logger.info(f"Updated pending Payment {payment.receipt_number} for admission #{admission.id}")

    # Synchronize admission status to 'approval_pending' if proof / transaction ref is provided or offline payment
    status_changed = False
    has_proof_or_offline = bool(
        admission.payment_screenshot or
        admission.transaction_id or
        pc in ('cash', 'cheque')
    )

    if has_proof_or_offline and admission.status in ('payment_pending', 'form_pending'):
        admission.status = 'approval_pending'
        if not admission.payment_submitted_at:
            admission.payment_submitted_at = timezone.now()
        admission.save(update_fields=['status', 'payment_submitted_at', 'updated_at'])
        status_changed = True

        AdmissionStatusHistory.objects.create(
            admission=admission,
            status='approval_pending',
            changed_by=getattr(request, 'user', None) if request and getattr(request, 'user', None) and request.user.is_authenticated else None,
            note=f"Payment details recorded. Transaction ID: {admission.transaction_id or 'N/A'}",
        )

        payment_history_data = {
            'payment_choice': admission.payment_choice or mapped_mode,
            'amount': float(pay_amount or 0),
            'transaction_id': admission.transaction_id or '',
            'status': 'approval_pending',
        }
        if new_payment:
            admission.add_payment_history_entry('payment_submitted', payment_history_data)
        else:
            admission.update_current_payment_history_entry('payment_submitted', payment_history_data)
    elif force and has_proof_or_offline:
        if not admission.payment_submitted_at:
            admission.payment_submitted_at = timezone.now()
            admission.save(update_fields=['payment_submitted_at', 'updated_at'])

        AdmissionStatusHistory.objects.create(
            admission=admission,
            status='approval_pending',
            changed_by=getattr(request, 'user', None) if request and getattr(request, 'user', None) and request.user.is_authenticated else None,
            note=f"Payment proof submitted. Transaction ID: {admission.transaction_id or 'N/A'}",
        )

        payment_history_data = {
            'payment_choice': admission.payment_choice or mapped_mode,
            'amount': float(pay_amount or 0),
            'transaction_id': admission.transaction_id or '',
            'status': 'approval_pending',
        }
        if new_payment:
            admission.add_payment_history_entry('payment_submitted', payment_history_data)
        else:
            admission.update_current_payment_history_entry('payment_submitted', payment_history_data)

    # Dispatch Level 1 WhatsApp approval notification if newly created with proof, status changed, or forced submission
    should_dispatch_l1 = (
        status_changed or
        (force and has_proof_or_offline) or
        (created and (admission.payment_screenshot or admission.transaction_id))
    )

    if should_dispatch_l1:
        try:
            from .notifications import send_payment_verification_whatsapp
            send_payment_verification_whatsapp(admission, level=1)
        except Exception as exc:
            logger.error(f"Failed to dispatch Level 1 WhatsApp payment notification for admission {admission.id}: {exc}")

        try:
            from core.utils import notify_users_by_role
            notify_users_by_role(
                roles=['accountant'],
                title='Admission Payment Proof Submitted',
                body=f"Payment details submitted for admission #{admission.id} ({admission.first_name} {admission.surname}). Level 1 approval required.",
                organization=admission.branch.organization if getattr(admission, 'branch', None) else None,
                branch=admission.branch if getattr(admission, 'branch', None) else None,
            )
        except Exception as exc:
            logger.error(f"Failed to dispatch Level 1 system notification for admission {admission.id}: {exc}")

    return payment