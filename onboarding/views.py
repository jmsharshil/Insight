from django.shortcuts import render

# Create your views here.
import logging

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .models import Admission
from .serializers import (
    AdmissionSerializer,
    AdmissionStatusUpdateSerializer,
    AdmissionListSerializer,
    AdmissionDetailSerializer,
    AdmissionUpdateSerializer,
)
from .utils import AdmissionService

logger = logging.getLogger(__name__)


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