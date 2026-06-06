from django.shortcuts import render

# Create your views here.
import logging
from core.pagination import paginate_queryset

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .models import Admission
from .serializers import (AdmissionSerializer,AdmissionStatusUpdateSerializer,AdmissionListSerializer,AdmissionDetailSerializer,AdmissionUpdateSerializer,AdmissionDocumentUploadSerializer,)
from .utils import AdmissionService

logger = logging.getLogger(__name__)

def _get_admission(request, admission_id):
    try:
        queryset = Admission.objects.select_related(
            'branch', 'assigned_counsellor', 'lead',
        )
        if getattr(request.user, 'organization', None):
            queryset = queryset.filter(branch__organization=request.user.organization)
        return queryset.get(id=admission_id)
    except Admission.DoesNotExist:
        return None
 
 
def _not_found():
    return Response(
        {'success': False, 'message': 'Admission not found.'},
        status=status.HTTP_404_NOT_FOUND,
    )

# ── POST /api/admissions/   — submit registration form
# ── GET  /api/admissions/   — list all admissions (with optional filters)
class AdmissionListView(APIView):

    def post(self, request):
        # Merge body + files
        data = request.data.dict() if hasattr(request.data, 'dict') else dict(request.data)
        data.update({k: v for k, v in request.FILES.items()})

        admission_id = data.get('id') or data.get('admission_id')

        if not admission_id:
            return Response(
                {
                    'success': False,
                    'message': 'id is required. Admissions are created automatically when a lead is converted.',
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Find admission by ID or by linked lead ID
        try:
            from django.db.models import Q
            admission = Admission.objects.filter(
                Q(id=admission_id) | Q(lead__id=admission_id)
            ).first()
            if not admission:
                return Response({'success': False, 'message': 'Admission not found for this ID.'}, status=status.HTTP_404_NOT_FOUND)

            # Check permissions if necessary
            if getattr(request.user, 'organization', None) and admission.branch and admission.branch.organization != request.user.organization:
                return Response({'success': False, 'message': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
            
            serializer = AdmissionUpdateSerializer(admission, data=data, partial=True)
            if not serializer.is_valid():
                return Response(
                    {'success': False, 'message': 'Please fix the errors below.', 'errors': serializer.errors},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            serializer.save()
        except Exception as e:
            logger.error(f"Admission update error: {e}")
            return Response(
                {'success': False, 'message': f'Something went wrong: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        counsellor_data = None
        if admission.assigned_counsellor:
            counsellor_data = {
                'id':    str(admission.assigned_counsellor.id),
                'name':  admission.assigned_counsellor.name,
                'email': admission.assigned_counsellor.email,
            }

        return Response(
            {
                'success': True,
                'message': (
                    'Your admission form has been submitted successfully. '
                    'It is now pending counsellor review. You will receive '
                    'login credentials once your admission is approved and enrolled.'
                ),
                'data': {
                    'admission_id':       admission.id,
                    'status':             admission.status,
                    'name':               f"{admission.first_name} {admission.surname}".strip(),
                    'assigned_counsellor': counsellor_data,
                },
            },
            status=status.HTTP_201_CREATED,
        )

    def get(self, request):
        queryset = Admission.objects.all()
        
        if getattr(request.user, 'organization', None):
            queryset = queryset.filter(branch__organization=request.user.organization)

        # Optional filters
        adm_status = request.GET.get('status')
        course     = request.GET.get('course')

        if adm_status:
            queryset = queryset.filter(status=adm_status)
        if course:
            queryset = queryset.filter(course=course)

        return paginate_queryset(queryset, request, AdmissionListSerializer)


# ── GET   /api/admissions/<id>/  — retrieve
# ── PUT   /api/admissions/<id>/  — full update
# ── PATCH /api/admissions/<id>/  — partial update
# ── DELETE /api/admissions/<id>/ — delete
class AdmissionDetailView(APIView):
    from rest_framework.permissions import AllowAny
    permission_classes = [AllowAny]

    def _get_admission(self, request, identifier):
        try:
            from django.db.models import Q
            queryset = Admission.objects.all()
            if getattr(request.user, 'organization', None):
                queryset = queryset.filter(
                    Q(branch__organization=request.user.organization) | Q(branch__isnull=True)
                )

            # Match either by admission's own ID or by the associated lead's ID
            return queryset.filter(Q(id=identifier) | Q(lead__id=identifier)).first()
        except Exception:
            return None

    def get(self, request, admission_id):
        admission = self._get_admission(request, admission_id)
        if admission is None:
            return Response(
                {'success': False, 'message': 'Admission not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(
            {'success': True, 'data': AdmissionDetailSerializer(admission).data},
            status=status.HTTP_200_OK,
        )

    def _update(self, request, admission_id, partial: bool):
        admission = self._get_admission(request, admission_id)
        if admission is None:
            return Response(
                {'success': False, 'message': 'Admission not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Check if the student has already filled out the form. 
        # (Auto-created admissions have dob=None until the student submits the form)
        if request.method == 'POST' and admission.dob is not None:
            return Response(
                {'success': False, 'message': 'You have already submitted this admission form.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = AdmissionUpdateSerializer(admission, data=request.data, partial=partial)
        if not serializer.is_valid():
            return Response(
                {'success': False, 'message': 'Please fix the errors below.', 'errors': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer.save()
        return Response(
            {'success': True, 'message': 'Admission updated successfully.',
             'data': AdmissionDetailSerializer(admission).data},
            status=status.HTTP_200_OK,
        )

    def put(self, request, admission_id):
        return self._update(request, admission_id, partial=False)

    def patch(self, request, admission_id):
        return self._update(request, admission_id, partial=True)

    def post(self, request, admission_id):
        return self._update(request, admission_id, partial=True)

    def delete(self, request, admission_id):
        admission = self._get_admission(request, admission_id)
        if admission is None:
            return Response(
                {'success': False, 'message': 'Admission not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        admission.delete()
        return Response(
            {'success': True, 'message': f'Admission {admission_id} deleted successfully.'},
            status=status.HTTP_200_OK,
        )


# ── PATCH /api/admissions/<id>/status/  — change admission status
class AdmissionStatusUpdateView(APIView):

    def patch(self, request, admission_id):
        try:
            queryset = Admission.objects.all()
            if getattr(request.user, 'organization', None):
                queryset = queryset.filter(branch__organization=request.user.organization)
            admission = queryset.get(id=admission_id)
        except Admission.DoesNotExist:
            return Response(
                {'success': False, 'message': 'Admission not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = AdmissionStatusUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {'success': False, 'errors': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        new_status = serializer.validated_data['status']
        note       = serializer.validated_data.get('note', '')

        AdmissionService.update_status(
            admission=admission,
            new_status=new_status,
            note=note,
            user=request.user if request.user.is_authenticated else None,
        )

        return Response(
            {
                'success': True,
                'message': 'Admission status updated successfully.',
                'data': {'admission_id': admission.id, 'status': admission.status, 'note': admission.note},
            },
            status=status.HTTP_200_OK,
        )
    

class AdmissionUpdateView(APIView):
 
    def patch(self, request, admission_id):
        admission = _get_admission(request, admission_id)
        if not admission:
            return _not_found()
 
        serializer = AdmissionUpdateSerializer(
            admission, data=request.data, partial=True
        )
        if not serializer.is_valid():
            return Response(
                {
                    'success': False,
                    'message': 'Validation failed.',
                    'errors' : serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
 
        serializer.save()
 
        return Response(
            {
                'success': True,
                'message': 'Admission updated successfully.',
                'data'   : AdmissionDetailSerializer(admission).data,
            },
            status=status.HTTP_200_OK,
        )
 
 
# ── POST /api/admissions/<id>/approve/ ───────────────────────────────────────
 
class AdmissionApproveView(APIView):
 
    def post(self, request, admission_id):
        admission = _get_admission(request, admission_id)
        if not admission:
            return _not_found()
 
        if admission.status == 'enrolled':
            return Response(
                {'success': False, 'message': 'Admission is already enrolled.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
 
        if admission.status == 'rejected':
            return Response(
                {
                    'success': False,
                    'message': (
                        'Rejected admissions cannot be approved directly. '
                        'Please update the status to pending first.'
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
 
        note        = request.data.get('note', 'Approved by counsellor.').strip()
        acting_user = request.user if request.user.is_authenticated else None

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # STEP 1: First Approval (pending → payment_pending)
        #   → Assign a bank account, send email with bank details + payment link
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        if admission.status in ('approval_pending', 'approved'):
            from .models import BANK_ACCOUNTS

            # Round-robin bank assignment based on admission ID
            bank_index = (admission.id - 1) % len(BANK_ACCOUNTS)
            assigned_bank = BANK_ACCOUNTS[bank_index]

            admission.assigned_bank_id = assigned_bank['id']
            admission.status = 'payment_pending'
            admission.note = note
            admission.save(update_fields=['assigned_bank_id', 'status', 'note', 'updated_at'])

            from .models import AdmissionStatusHistory
            AdmissionStatusHistory.objects.create(
                admission=admission,
                status='payment_pending',
                changed_by=acting_user,
                note=note,
            )

            # Send email with bank details + payment upload link
            if admission.email:
                try:
                    from core.email import send_email
                    payment_link = f"http://localhost:5173/insight/student/payment-upload?id={admission.id}"

                    text_content = (
                        f"Hello {admission.first_name},\n\n"
                        f"Congratulations! Your admission has been approved. "
                        f"Please complete your fee payment to finalize your enrollment.\n\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"BANK DETAILS FOR FEE PAYMENT\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"Bank Name       : {assigned_bank['bank_name']}\n"
                        f"Account Holder  : {assigned_bank['account_holder']}\n"
                        f"Account Number  : {assigned_bank['account_number']}\n"
                        f"IFSC Code       : {assigned_bank['ifsc_code']}\n"
                        f"Branch          : {assigned_bank['branch']}\n"
                        f"Account Type    : {assigned_bank['account_type']}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                        f"After making the payment, please click the link below to "
                        f"upload your payment screenshot and transaction ID:\n\n"
                        f"{payment_link}\n\n"
                        f"If you have any questions, feel free to reach out to your counsellor.\n\n"
                        f"Best Regards,\n"
                        f"Insight Institute Team"
                    )

                    send_email(
                        to=admission.email,
                        subject="Admission Approved - Complete Your Fee Payment",
                        text=text_content,
                        template=None,
                        template_context={},
                        organization=admission.branch.organization if getattr(admission, 'branch', None) else None,
                    )
                    logger.info(f"Payment email sent to {admission.email} with bank: {assigned_bank['bank_name']}")
                except Exception as e:
                    logger.error(f"Failed to send payment email to {admission.email}: {e}")

            return Response(
                {
                    'success': True,
                    'message': (
                        'Admission approved. Bank details email sent to student. '
                        'Waiting for fee payment confirmation.'
                    ),
                    'data': {
                        'admission_id': admission.id,
                        'status': admission.status,
                        'status_display': admission.get_status_display(),
                        'assigned_bank': assigned_bank,
                    },
                },
                status=status.HTTP_200_OK,
            )

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # STEP 2: Second Approval (payment_submitted → enrolled)
        #   → Verify payment, create user accounts + student profile
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        if admission.status == 'payment_submitted':
            try:
                AdmissionService.update_status(
                    admission  = admission,
                    new_status = 'enrolled',
                    note       = note,
                    user       = acting_user,
                )
            except Exception as exc:
                logger.error(f"AdmissionService.update_status failed for {admission_id}: {exc}")
                return Response(
                    {'success': False, 'message': f'Enrolment failed: {exc}'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
 
            from auth_user.models import User
            student_user = User.objects.filter(
                email=admission.email, role='student'
            ).first()
 
            if not student_user:
                logger.error(
                    f"Student user account missing for admission {admission_id} "
                    f"(email={admission.email}) after enrolment."
                )
                return Response(
                    {
                        'success': False,
                        'message': (
                            'Admission status set to enrolled but student user account '
                            'was not found. Please check server logs.'
                        ),
                        'data': {
                            'admission_id'    : admission.id,
                            'admission_status': admission.status,
                            'status_display'  : admission.get_status_display(),
                        },
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
 
            try:
                from students.utils import StudentService
                student = StudentService.create_from_admission(
                    admission   = admission,
                    user        = student_user,
                    acting_user = acting_user,
                )
            except Exception as exc:
                logger.error(
                    f"StudentService.create_from_admission failed for admission "
                    f"{admission_id}: {exc}"
                )
                return Response(
                    {
                        'success': False,
                        'message': (
                            'Admission enrolled and user accounts created, but student '
                            f'profile creation failed: {exc}'
                        ),
                        'data': {
                            'admission_id'    : admission.id,
                            'admission_status': admission.status,
                            'status_display'  : admission.get_status_display(),
                        },
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
 
            return Response(
                {
                    'success': True,
                    'message': (
                        f"Payment verified. Admission approved and student enrolled. "
                        f"Admission number: {student.admission_number}. "
                        f"Login credentials dispatched to student and parent."
                    ),
                    'data': {
                        'admission_id'    : admission.id,
                        'admission_status': admission.status,
                        'status_display'  : admission.get_status_display(),
                        'student_id'      : str(student.id),
                        'admission_number': student.admission_number,
                        'student_status'  : student.status,
                    },
                },
                status=status.HTTP_200_OK,
            )

        # ── Status not eligible for approval ──────────────────────────────────
        if admission.status == 'payment_pending':
            return Response(
                {
                    'success': False,
                    'message': 'Waiting for student to submit payment proof. Cannot approve yet.',
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {'success': False, 'message': f"Cannot approve admission with status '{admission.status}'."},
            status=status.HTTP_400_BAD_REQUEST,
        )


# ── POST /api/admissions/<id>/payment/ — Student uploads payment proof ────────

class AdmissionPaymentSubmitView(APIView):
    """
    Public endpoint (no auth required).
    Student opens the email link and submits payment screenshot + transaction ID.
    """
    from rest_framework.permissions import AllowAny

    def get_permissions(self):
        from rest_framework.permissions import AllowAny
        return [AllowAny()]

    def post(self, request, admission_id):
        from django.db.models import Q

        try:
            admission = Admission.objects.filter(
                Q(id=admission_id) | Q(lead__id=admission_id)
            ).first()
        except Exception:
            admission = None

        if not admission:
            return Response(
                {'success': False, 'message': 'Admission not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if admission.status != 'payment_pending':
            return Response(
                {
                    'success': False,
                    'message': f"Payment upload is not expected at this stage. Current status: '{admission.status}'.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        from .serializers import PaymentSubmitSerializer
        serializer = PaymentSubmitSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {'success': False, 'message': 'Please fix the errors below.', 'errors': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from django.utils import timezone
        admission.payment_screenshot   = serializer.validated_data['payment_screenshot']
        admission.transaction_id       = serializer.validated_data['transaction_id']
        admission.payment_note         = serializer.validated_data.get('payment_note', '')
        admission.payment_submitted_at = timezone.now()
        admission.status               = 'payment_submitted'
        admission.save(update_fields=[
            'payment_screenshot', 'transaction_id', 'payment_note',
            'payment_submitted_at', 'status', 'updated_at',
        ])

        from .models import AdmissionStatusHistory
        AdmissionStatusHistory.objects.create(
            admission=admission,
            status='payment_submitted',
            changed_by=None,
            note=f"Payment proof submitted by student. Transaction ID: {admission.transaction_id}",
        )

        logger.info(
            f"Payment proof submitted for admission {admission.id} — "
            f"Transaction ID: {admission.transaction_id}"
        )

        return Response(
            {
                'success': True,
                'message': (
                    'Payment proof submitted successfully! '
                    'Your counsellor will verify the payment and complete your enrollment. '
                    'You will receive your login credentials via email once approved.'
                ),
                'data': {
                    'admission_id':   admission.id,
                    'status':         admission.status,
                    'status_display': admission.get_status_display(),
                    'transaction_id': admission.transaction_id,
                },
            },
            status=status.HTTP_200_OK,
        )
 
 
# ── POST /api/admissions/<id>/reject/ ────────────────────────────────────────
 
class AdmissionRejectView(APIView):
 
    def post(self, request, admission_id):
        admission = _get_admission(request, admission_id)
        if not admission:
            return _not_found()
 
        if admission.status == 'enrolled':
            return Response(
                {'success': False, 'message': 'Enrolled admissions cannot be rejected.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
 
        if admission.status == 'rejected':
            return Response(
                {'success': False, 'message': 'Admission is already rejected.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
 
        reason = request.data.get('reason', '').strip()
        if not reason:
            return Response(
                {
                    'success': False,
                    'message': "'reason' is required when rejecting an admission.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        
        AdmissionService.update_status(
            admission  = admission,
            new_status = 'rejected',
            note       = reason,
            user       = request.user if request.user.is_authenticated else None,
        )
 
        return Response(
            {
                'success': True,
                'message': 'Admission rejected.',
                'data': {
                    'admission_id': admission.id,
                    'status'      : admission.status,
                    'reason'      : reason,
                },
            },
            status=status.HTTP_200_OK,
        )
 
 
# ── POST /api/admissions/<id>/documents/ ─────────────────────────────────────
 
class AdmissionDocumentUploadView(APIView):
 
    def post(self, request, admission_id):
        admission = _get_admission(request, admission_id)
        if not admission:
            return _not_found()
 
        serializer = AdmissionDocumentUploadSerializer(
            data={
                'field_name': request.data.get('field_name'),
                'file'      : request.FILES.get('file'),
            }
        )
        if not serializer.is_valid():
            return Response(
                {'success': False, 'errors': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
 
        field_name = serializer.validated_data['field_name']
        file       = serializer.validated_data['file']
 
        # Direct save — no service indirection needed for a simple field swap
        setattr(admission, field_name, file)
        admission.save(update_fields=[field_name, 'updated_at'])
 
        logger.info(
            f"Document '{field_name}' uploaded for admission {admission_id} "
            f"by user {getattr(request.user, 'id', 'anonymous')}."
        )
 
        return Response(
            {
                'success': True,
                'message': f"Document '{field_name}' uploaded successfully.",
                'data'   : {
                    'admission_id': admission.id,
                    'field_name'  : field_name,
                    'file_name'   : file.name,
                },
            },
            status=status.HTTP_200_OK,
        )