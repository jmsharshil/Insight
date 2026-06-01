"""
─────────────────────
All business-logic for the Student module.
Views stay thin — they only validate input and delegate here.
"""

import io
import logging
import qrcode

from django.db import transaction
from django.utils import timezone

from .models import (
    Student,
    ParentLink,
    BatchHistory,
    DigitalIDCard,
    StudentStatusHistory,
)

logger = logging.getLogger(__name__)


class StudentService:

    # ── Create Student from Admission ─────────────────────────────────────────

    @staticmethod
    @transaction.atomic
    def create_from_admission(admission, user, acting_user=None) -> Student:
        """
        Called when an admission is set to 'enrolled'.
        Creates the Student master profile, links it to the login user account,
        and generates the digital ID card if a photo is available.
        """
        if hasattr(admission, 'student_profile'):
            logger.warning(
                f"Attempted to create duplicate student for admission {admission.id}"
            )
            return admission.student_profile

        student = Student(
            admission           = admission,
            user                = user,
            branch              = admission.branch,
            assigned_counsellor = admission.assigned_counsellor,

            # Personal
            first_name  = admission.first_name,
            surname     = admission.surname,
            father_name = admission.father_name,
            mother_name = admission.mother_name,
            dob         = admission.dob,
            category    = admission.category,

            # Contact
            email           = admission.email,
            email_parent    = admission.email_parent,
            phone_student   = admission.phone_student,
            phone_student_2 = admission.phone_student_2,
            phone_father    = admission.phone_father,
            phone_father_2  = admission.phone_father_2,

            # Address
            street    = admission.street,
            apartment = admission.apartment,
            city      = admission.city,
            state     = admission.state,
            pincode   = admission.pincode,
            country   = admission.country,

            # Academic
            course        = admission.course,
            group_module  = admission.group_module,
            batch_attempt = admission.batch_attempt,
            qualification = admission.qualification,
            location      = admission.location,

            status      = 'active',
            enrolled_at = timezone.now(),
        )
        student.save()   # triggers admission_number generation

        # Copy documents across
        doc_mapping = {
            'doc_signature': 'doc_signature',
            'doc_photo': 'photo',
            'doc_dob_certificate': 'doc_dob_certificate',
            'doc_id_card': 'doc_id_proof',
            'doc_twelfth_marksheet': 'doc_twelfth_marksheet',
            'doc_category_cert': 'doc_category_cert',
        }
        for adm_field, std_field in doc_mapping.items():
            src = getattr(admission, adm_field, None)
            if src:
                setattr(student, std_field, src)
        student.save()

        # Link parent user(s) to this student profile
        for parent_user in user.linked_parents.all():
            ParentLink.objects.create(
                student=student,
                parent=parent_user,
                relationship='father', # default relationship
                is_primary=True,
            )

        # Record initial status history
        StudentStatusHistory.objects.create(
            student    = student,
            old_status = 'active',
            new_status = 'active',
            reason     = 'Student enrolled via admission approval.',
            changed_by = acting_user,
        )

        # Auto-generate digital ID card
        try:
            StudentService.generate_id_card(student)
        except Exception as exc:
            logger.error(f"ID card generation failed for student {student.id}: {exc}")

        logger.info(f"Student created: {student.admission_number} from admission {admission.id}")
        return student

    # ── Update Student Status ─────────────────────────────────────────────────

    @staticmethod
    @transaction.atomic
    def update_status(student: Student, new_status: str, reason: str = '', acting_user=None):
        old_status     = student.status
        student.status = new_status
        student.save(update_fields=['status', 'updated_at'])

        StudentStatusHistory.objects.create(
            student    = student,
            old_status = old_status,
            new_status = new_status,
            reason     = reason,
            changed_by = acting_user,
        )

        # Deactivate ID card if student is no longer active
        if new_status != 'active':
            DigitalIDCard.objects.filter(student=student).update(is_active=False)

        logger.info(
            f"Student {student.admission_number} status: {old_status} → {new_status}"
        )
        return student

    # ── Allocate Batch ────────────────────────────────────────────────────────

    @staticmethod
    @transaction.atomic
    def allocate_batch(student: Student, batch_name: str, reason: str = '', acting_user=None):
        """Assign or change a student's batch; always logs the change."""
        student.current_batch_name = batch_name
        student.save(update_fields=['current_batch_name', 'updated_at'])

        BatchHistory.objects.create(
            student    = student,
            batch_name = batch_name,
            reason     = reason,
            changed_by = acting_user,
        )

        logger.info(
            f"Student {student.admission_number} allocated to batch '{batch_name}'"
        )
        return student

    # ── Upload / Replace Document ─────────────────────────────────────────────

    @staticmethod
    def upload_document(record, field_name: str, file):
        """
        Generic document upload for both Admission and Student records.
        Replaces any existing file for that field.
        """
        if not hasattr(record, field_name):
            raise ValueError(f"Field '{field_name}' does not exist on {type(record).__name__}.")
        setattr(record, field_name, file)
        record.save(update_fields=[field_name, 'updated_at'])
        return record

    # ── Generate / Regenerate Digital ID Card ─────────────────────────────────

    @staticmethod
    def generate_id_card(student: Student) -> DigitalIDCard:
        """
        Creates (or regenerates) a DigitalIDCard for the student.
        Requires student.photo to be present.
        QR payload = str(student.id)  — scanned at attendance check-in.
        """
        if not student.has_photo:
            raise ValueError(
                f"Cannot generate ID card for {student.admission_number}: "
                "profile photo is required."
            )

        qr_payload = str(student.id)

        # Generate QR image in-memory
        qr = qrcode.QRCode(
            version            = 1,
            error_correction   = qrcode.constants.ERROR_CORRECT_M,
            box_size           = 10,
            border             = 4,
        )
        qr.add_data(qr_payload)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white")

        # Save QR image to an in-memory buffer
        buffer = io.BytesIO()
        qr_img.save(buffer, format='PNG')
        buffer.seek(0)

        from django.core.files.base import ContentFile

        id_card, created = DigitalIDCard.objects.get_or_create(
            student  = student,
            defaults = {'qr_data': qr_payload, 'is_active': True},
        )

        if not created:
            id_card.regenerated_at = timezone.now()
            id_card.is_active      = True

        id_card.qr_data = qr_payload
        id_card.qr_image.save(
            f"{student.admission_number}_qr.png",
            ContentFile(buffer.read()),
            save=False,
        )

        # ── Generate Full Visual ID Card ──
        try:
            from PIL import Image, ImageDraw, ImageFont
            import os

            # Canvas dimensions (portrait)
            card = Image.new('RGB', (400, 600), color='white')
            draw = ImageDraw.Draw(card)

            # Header
            draw.rectangle([(0, 0), (400, 80)], fill=(30, 64, 175))
            
            try:
                # Attempt to use basic fonts on Windows
                title_font = ImageFont.truetype("arial.ttf", 22)
                label_font = ImageFont.truetype("arial.ttf", 14)
                value_font = ImageFont.truetype("arialbd.ttf", 16)
            except IOError:
                # Fallback to default
                title_font = ImageFont.load_default()
                label_font = ImageFont.load_default()
                value_font = ImageFont.load_default()

            # Header Text
            draw.text((200, 40), "STUDENT ID CARD", font=title_font, fill='white', anchor="mm")

            # Paste Student Photo
            if student.photo and hasattr(student.photo, 'path') and os.path.exists(student.photo.path):
                try:
                    photo_img = Image.open(student.photo.path).convert("RGBA")
                    # Crop center and resize to 120x120
                    w, h = photo_img.size
                    min_dim = min(w, h)
                    left = (w - min_dim) / 2
                    top = (h - min_dim) / 2
                    photo_img = photo_img.crop((left, top, left + min_dim, top + min_dim))
                    photo_img = photo_img.resize((120, 120), Image.Resampling.LANCZOS)
                    # Paste onto white background to drop alpha
                    bg = Image.new("RGB", photo_img.size, (255, 255, 255))
                    bg.paste(photo_img, mask=photo_img.split()[3])
                    card.paste(bg, (140, 100))
                except Exception as e:
                    logger.error(f"Failed to process photo for ID card: {e}")

            # Draw Student Info
            start_y = 250
            line_height = 40
            info = [
                ("Name:", student.full_name),
                ("Admission No:", student.admission_number),
                ("Course:", student.course),
                ("Batch:", student.current_batch_name or "Not Assigned"),
            ]
            for i, (label, value) in enumerate(info):
                y = start_y + (i * line_height)
                draw.text((40, y), label, font=label_font, fill=(107, 114, 128))  # gray-500
                draw.text((150, y), str(value), font=value_font, fill=(17, 24, 39))  # gray-900

            # Paste QR Code
            qr_display = qr_img.resize((120, 120), Image.Resampling.LANCZOS)
            card.paste(qr_display, (140, 420))

            # Footer
            draw.rectangle([(0, 560), (400, 600)], fill=(243, 244, 246))
            draw.text((200, 580), "Insight Institute", font=label_font, fill=(107, 114, 128), anchor="mm")

            # Save full card to buffer
            card_buffer = io.BytesIO()
            card.save(card_buffer, format='PNG')
            card_buffer.seek(0)
            
            id_card.card_image.save(
                f"{student.admission_number}_card.png",
                ContentFile(card_buffer.read()),
                save=False,
            )
        except Exception as e:
            logger.error(f"Failed to generate full visual ID card: {e}")

        id_card.save()

        logger.info(f"ID card {'created' if created else 'regenerated'} for {student.admission_number}")
        return id_card

    # ── Build QR Identity Payload ─────────────────────────────────────────────

    @staticmethod
    def get_qr_identity_data(student: Student, request=None) -> dict:
        """
        Returns the dict consumed by QRIdentitySerializer.
        Generates the ID card on-the-fly if missing and photo is available.
        """
        def abs_url(field):
            if field and request:
                return request.build_absolute_uri(field.url)
            return None

        id_card = None
        if not hasattr(student, 'id_card') or student.id_card is None:
            if student.has_photo:
                try:
                    id_card = StudentService.generate_id_card(student)
                except Exception as exc:
                    logger.error(f"On-demand ID card generation failed: {exc}")
        else:
            id_card = student.id_card

        return {
            'student_id'       : student.id,
            'admission_number' : student.admission_number,
            'full_name'        : student.full_name,
            'course'           : student.course,
            'batch_name': student.current_batch_name or None,
            'branch_name'      : student.branch.name if student.branch else None,
            'photo_url'        : abs_url(student.photo),
            'qr_payload'       : str(student.id),
            'qr_image_url'     : abs_url(id_card.qr_image) if id_card else None,
            'card_image_url'   : abs_url(id_card.card_image) if id_card else None,
            'generated_at'     : id_card.generated_at if id_card else None,
            'is_active'        : id_card.is_active if id_card else False,
        }