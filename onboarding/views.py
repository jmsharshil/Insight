from django.shortcuts import render

# Create your views here.
import logging

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .models import Admission
from .serializers import (AdmissionSerializer,AdmissionStatusUpdateSerializer,AdmissionListSerializer,AdmissionDetailSerializer,AdmissionUpdateSerializer,AdmissionDocumentUploadSerializer,)
from .utils import AdmissionService

logger = logging.getLogger(__name__)

def _get_admission(admission_id):
    try:
        return Admission.objects.select_related(
            'branch', 'assigned_counsellor', 'lead',
        ).get(id=admission_id)
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

        serializer = AdmissionSerializer(data=data)
        if not serializer.is_valid():
            logger.warning(f"Admission validation failed: {serializer.errors}")
            return Response(
                {
                    'success': False,
                    'message': 'Please fix the errors below.',
                    'errors': serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            admission = AdmissionService.create_admission(
                validated_data=serializer.validated_data,
                user=request.user if request.user.is_authenticated else None,
            )
        except Exception as e:
            logger.error(f"Admission creation error: {e}")
            return Response(
                {'success': False, 'message': 'Something went wrong. Please try again.'},
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

        # Optional filters
        adm_status = request.GET.get('status')
        course     = request.GET.get('course')

        if adm_status:
            queryset = queryset.filter(status=adm_status)
        if course:
            queryset = queryset.filter(course=course)

        serializer = AdmissionListSerializer(queryset, many=True)
        return Response(
            {'success': True, 'count': queryset.count(), 'data': serializer.data},
            status=status.HTTP_200_OK,
        )


# ── GET   /api/admissions/<id>/  — retrieve
# ── PUT   /api/admissions/<id>/  — full update
# ── PATCH /api/admissions/<id>/  — partial update
# ── DELETE /api/admissions/<id>/ — delete
class AdmissionDetailView(APIView):

    def _get_admission(self, admission_id):
        try:
            return Admission.objects.get(id=admission_id)
        except Admission.DoesNotExist:
            return None

    def get(self, request, admission_id):
        admission = self._get_admission(admission_id)
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
        admission = self._get_admission(admission_id)
        if admission is None:
            return Response(
                {'success': False, 'message': 'Admission not found.'},
                status=status.HTTP_404_NOT_FOUND,
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

    def delete(self, request, admission_id):
        admission = self._get_admission(admission_id)
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
            admission = Admission.objects.get(id=admission_id)
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
        admission = _get_admission(admission_id)
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
        admission = _get_admission(admission_id)
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
 
        # ── Step 1: AdmissionService handles status + user account creation ──
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
                    },
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
 
        # ── Step 3: Create Student master profile (students app) ─────────────
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
                    },
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
 
        return Response(
            {
                'success': True,
                'message': (
                    f"Admission approved and student enrolled. "
                    f"Admission number: {student.admission_number}. "
                    f"Login credentials dispatched to student and parent."
                ),
                'data': {
                    'admission_id'    : admission.id,
                    'admission_status': admission.status,
                    'student_id'      : str(student.id),
                    'admission_number': student.admission_number,
                    'student_status'  : student.status,
                },
            },
            status=status.HTTP_200_OK,
        )
 
 
# ── POST /api/admissions/<id>/reject/ ────────────────────────────────────────
 
class AdmissionRejectView(APIView):
 
    def post(self, request, admission_id):
        admission = _get_admission(admission_id)
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
        admission = _get_admission(admission_id)
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