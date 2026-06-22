from django.shortcuts import render

# Create your views here.

import logging
from core.pagination import paginate_queryset

from django.db.models import Q
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.filters import SearchFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend

from core.utils import apply_filters

from .models import Student, InventoryIssue
from .serializers import (StudentListSerializer,StudentDetailSerializer,StudentSelfProfileSerializer,StudentUpdateSerializer,StudentStatusUpdateSerializer,BatchAllocateSerializer,DocumentUploadSerializer,InventoryIssueCreateSerializer,InventoryIssueReadSerializer,QRIdentitySerializer,)
from .utils import StudentService

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_student(request, student_id):
    try:
        queryset = Student.objects.select_related(
            'branch', 'assigned_counsellor', 'user', 'admission', 'id_card',
        ).prefetch_related(
            'parent_links__parent',
            'batch_history',
            'inventory_issues',
            'status_history',
        )
        if getattr(request.user, 'organization', None):
            queryset = queryset.filter(branch__organization=request.user.organization)
        
        try:
            return queryset.get(id=student_id)
        except Student.DoesNotExist:
            # Fallback to check if student_id is actually a user ID
            from django.contrib.auth import get_user_model
            User = get_user_model()
            if User.objects.filter(id=student_id).exists():
                return queryset.get(user_id=student_id)
            raise
    except Student.DoesNotExist:
        return None


def _not_found(student_id):
    return Response(
        {'success': False, 'message': f'Student {student_id} not found.'},
        status=status.HTTP_404_NOT_FOUND,
    )


# ── GET  /api/students/  — list ───────────────────────────────────────────────

class StudentListView(APIView):
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['status', 'course', 'branch', 'current_batch_name']
    search_fields = ['first_name', 'surname', 'admission_number', 'email', 'phone_student']
    ordering_fields = '__all__'

    def get(self, request):
        qs = Student.objects.select_related('branch').all()
        if getattr(request.user, 'organization', None):
            qs = qs.filter(branch__organization=request.user.organization)

        # Retain custom param mapping for backwards compatibility
        batch_name = request.GET.get('batch')
        if batch_name:
            qs = qs.filter(current_batch_name=batch_name)

        qs = apply_filters(self, request, qs)

        return paginate_queryset(qs, request, StudentListSerializer, serializer_context={'request': request})


# ── GET / PATCH  /api/students/<id>/ ─────────────────────────────────────────

class StudentDetailView(APIView):

    def get(self, request, student_id):
        student = _get_student(request, student_id)
        if not student:
            return _not_found(student_id)

        serializer = StudentDetailSerializer(student, context={'request': request})
        return Response({'success': True, 'data': serializer.data}, status=status.HTTP_200_OK)

    def patch(self, request, student_id):
        student = _get_student(request, student_id)
        if not student:
            return _not_found(student_id)

        serializer = StudentUpdateSerializer(student, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(
                {'success': False, 'message': 'Validation failed.', 'errors': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer.save()
        return Response(
            {
                'success': True,
                'message': 'Student profile updated.',
                'data': StudentDetailSerializer(student, context={'request': request}).data,
            },
            status=status.HTTP_200_OK,
        )
    
    def delete(self, request, student_id):
        student = _get_student(request, student_id)
        if not student:
            return _not_found(student_id)
        student.delete()
        return Response(
            {
                "success": True,
                "message": "Student deleted successfully."
            },
            status=status.HTTP_200_OK,
        )


# ── GET  /api/students/<id>/profile/  — self-profile ─────────────────────────

class StudentSelfProfileView(APIView):

    def get(self, request, student_id):
        student = _get_student(request, student_id)
        if not student:
            return _not_found(student_id)

        serializer = StudentSelfProfileSerializer(student, context={'request': request})
        return Response({'success': True, 'data': serializer.data}, status=status.HTTP_200_OK)


# ── GET  /api/students/<id>/qr-id/ ───────────────────────────────────────────

class StudentQRIdentityView(APIView):

    def get(self, request, student_id):
        student = _get_student(request, student_id)
        if not student:
            return _not_found(student_id)

        if not student.id_card_ready:
            return Response(
                {
                    'success': False,
                    'message': (
                        'QR identity pass cannot be generated: '
                        'profile photo is required. '
                        'Please upload a photo via PATCH /api/students/<id>/documents/.'
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            data = StudentService.get_qr_identity_data(student, request=request)
        except Exception as exc:
            logger.error(f"QR generation error for student {student_id}: {exc}")
            return Response(
                {'success': False, 'message': 'Could not generate QR pass. Please try again.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        serializer = QRIdentitySerializer(data)
        return Response({'success': True, 'data': serializer.data}, status=status.HTTP_200_OK)


# ── POST /api/students/<id>/regenerate-id-card/ ───────────────────────────────

class StudentRegenerateIDCardView(APIView):

    def post(self, request, student_id):
        student = _get_student(request, student_id)
        if not student:
            return _not_found(student_id)

        if not student.has_photo:
            return Response(
                {'success': False, 'message': 'Student does not have a photo uploaded. Cannot generate ID card.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Delete existing card so it regenerates fresh
        from .models import DigitalIDCard
        DigitalIDCard.objects.filter(student=student).delete()

        try:
            id_card = StudentService.generate_id_card(student)
        except Exception as exc:
            logger.error(f"ID card regeneration error for student {student_id}: {exc}")
            return Response(
                {'success': False, 'message': f'ID card regeneration failed: {exc}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            {
                'success': True,
                'message': 'ID card regenerated successfully.',
                'data': {
                    'qr_image': request.build_absolute_uri(id_card.qr_image.url) if id_card.qr_image else None,
                    'card_image': request.build_absolute_uri(id_card.card_image.url) if id_card.card_image else None,
                },
            },
            status=status.HTTP_200_OK,
        )


# ── POST /api/students/<id>/status/ ──────────────────────────────────────────

class StudentStatusUpdateView(APIView):

    def post(self, request, student_id):
        student = _get_student(request, student_id)
        if not student:
            return _not_found(student_id)

        serializer = StudentStatusUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {'success': False, 'errors': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        student = StudentService.update_status(
            student      = student,
            new_status   = serializer.validated_data['status'],
            reason       = serializer.validated_data.get('reason', ''),
            acting_user  = request.user if request.user.is_authenticated else None,
        )

        return Response(
            {
                'success': True,
                'message': f"Student status updated to '{student.status}'.",
                'data': {
                    'student_id'      : student.id,
                    'admission_number': student.admission_number,
                    'status'          : student.status,
                },
            },
            status=status.HTTP_200_OK,
        )


# ── POST /api/students/<id>/batch/ ────────────────────────────────────────────

class StudentBatchAllocateView(APIView):

    def post(self, request, student_id):
        student = _get_student(request, student_id)
        if not student:
            return _not_found(student_id)

        serializer = BatchAllocateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {'success': False, 'errors': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        batch_name = serializer.validated_data['batch_name']
        reason     = serializer.validated_data.get('reason', '')

        student = StudentService.allocate_batch(
            student     = student,
            batch_name  = batch_name,
            reason      = reason,
            acting_user = request.user if request.user.is_authenticated else None,
        )

        return Response(
            {
                'success': True,
                'message': f"Student allocated to batch '{batch_name}'.",
                'data': {
                    'student_id'  : student.id,
                    'batch_name'  : batch_name,
                },
            },
            status=status.HTTP_200_OK,
        )


# ── POST /api/students/<id>/documents/ ───────────────────────────────────────

class StudentDocumentUploadView(APIView):

    def post(self, request, student_id):
        student = _get_student(request, student_id)
        if not student:
            return _not_found(student_id)

        data = {'field_name': request.data.get('field_name'), 'file': request.FILES.get('file')}
        serializer = DocumentUploadSerializer(data=data)
        if not serializer.is_valid():
            return Response(
                {'success': False, 'errors': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        field_name = serializer.validated_data['field_name']
        file       = serializer.validated_data['file']

        try:
            StudentService.upload_document(student, field_name, file)
        except ValueError as exc:
            return Response(
                {'success': False, 'message': str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # If a photo was uploaded, attempt to (re)generate the ID card
        if field_name == 'photo':
            try:
                StudentService.generate_id_card(student)
            except Exception as exc:
                logger.warning(f"ID card regeneration after photo upload failed: {exc}")

        return Response(
            {
                'success': True,
                'message': f"Document '{field_name}' uploaded successfully.",
                'data'   : {'field_name': field_name},
            },
            status=status.HTTP_200_OK,
        )


# ── GET / POST  /api/students/<id>/inventory/ ────────────────────────────────

class StudentInventoryView(APIView):

    def get(self, request, student_id):
        student = _get_student(request, student_id)
        if not student:
            return _not_found(student_id)

        items = InventoryIssue.objects.filter(student=student).select_related('issued_by')
        serializer = InventoryIssueReadSerializer(items, many=True)
        return Response(
            {'success': True, 'count': items.count(), 'data': serializer.data},
            status=status.HTTP_200_OK,
        )

    def post(self, request, student_id):
        student = _get_student(request, student_id)
        if not student:
            return _not_found(student_id)

        serializer = InventoryIssueCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {'success': False, 'errors': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        issue = InventoryIssue.objects.create(
            student   = student,
            issued_by = request.user if request.user.is_authenticated else None,
            **serializer.validated_data,
        )

        return Response(
            {
                'success': True,
                'message': 'Inventory item issued.',
                'data'   : InventoryIssueReadSerializer(issue).data,
            },
            status=status.HTTP_201_CREATED,
        )