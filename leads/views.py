import logging

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.exceptions import ValidationError

from .serializers import get_lead_serializer, LeadStageUpdateSerializer, LeadListSerializer, LeadDetailSerializer, LeadUpdateSerializer
from .utils import LeadService
from .models import Lead,LeadStage
from django.db.models import Q
import re

from auth_user.models import User
from auth_user.utils import (
    generate_temporary_password,
    send_parent_login_credentials,
    send_student_login_credentials,
)

logger = logging.getLogger(__name__)


class LeadListView(APIView):

    def post(self, request):

        form_type = request.data.get('form_type')

        if not form_type:
            return Response(
                {
                    "success": False,
                    "message": "form_type is required.",
                    "errors": {"form_type": ["This field is required."]}
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            serializer = get_lead_serializer(
                form_type=form_type,
                data=request.data,
                files=request.FILES or None
            )
        except ValidationError as e:
            return Response(
                {
                    "success": False,
                    "message": "Invalid form type.",
                    "errors": e.detail
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        if not serializer.is_valid():
            logger.warning(
                f"Lead validation failed — form_type: {form_type} | "
                f"errors: {serializer.errors}"
            )
            return Response(
                {
                    "success": False,
                    "message": "Please fix the errors below.",
                    "errors": serializer.errors
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        validated_data = serializer.validated_data

        first_name = validated_data.get("first_name", "").strip()
        surname = validated_data.get("surname", "").strip()

        email = validated_data.get("email", "")
        email = email.strip().lower() if email else ""

        phone_student = validated_data.get("phone_student", "")
        phone_student = re.sub(r"\D", "", phone_student)

        course = validated_data.get("course")

        duplicate_lead = Lead.objects.filter(
            first_name__iexact=first_name,
            surname__iexact=surname,
            course=course
        ).filter(
            Q(email__iexact=email) |
            Q(phone_student=phone_student)
        ).first()

        try:
            lead = LeadService.create_lead(validated_data=validated_data, user=None)
        except Exception as e:
            logger.error(f"Lead creation error — {str(e)}")
            return Response(
                {
                    "success": False,
                    "message": "Something went wrong. Please try again.",
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        tag = "duplicate" if duplicate_lead else "new"

        return Response(
            {
                "success": True,
                "message": "Thank you! Your inquiry has been received. We will contact you shortly.",
                "tag": tag,
                "data": {
                    "lead_id":   lead.id,
                    "form_type": lead.form_type,
                    "name":      lead.first_name,
                    "stage":     lead.current_stage,
                }
            },
            status=status.HTTP_201_CREATED
        )

    def get(self, request):

        queryset = Lead.objects.all().order_by("-created_at")

        # Optional filters
        stage = request.GET.get("stage")
        course = request.GET.get("course")
        form_type = request.GET.get("form_type")

        if stage:
            queryset = queryset.filter(current_stage=stage)

        if course:
            queryset = queryset.filter(course=course)

        if form_type:
            queryset = queryset.filter(form_type=form_type)

        serializer = LeadListSerializer(queryset, many=True)

        return Response(
            {
                "success": True,
                "count": queryset.count(),
                "data": serializer.data
            },
            status=status.HTTP_200_OK
        )

class LeadStatusUpdateView(APIView):
    def _build_unique_username(self, email):
        base_username = email.split('@')[0].strip() or 'student'
        username = base_username
        counter = 1

        while User.objects.filter(username=username).exists():
            username = f"{base_username}{counter}"
            counter += 1

        return username

    def _create_or_update_user(self, *, email, phone, name, role, linked_student=None):
        if not email:
            raise ValueError("Email is required to create login credentials.")

        if not phone:
            raise ValueError("Phone is required to create login credentials.")

        password = generate_temporary_password()
        user = User.objects.filter(email=email).first()

        if user:
            if User.objects.filter(phone=phone).exclude(id=user.id).exists():
                raise ValueError(f"Phone number {phone} is already used by another account.")

            if not user.username:
                user.username = self._build_unique_username(email)

            user.phone = phone
            user.name = name or user.name
            user.role = role
            user.is_active = True
            user.linked_student = linked_student
            user.set_password(password)
            user.save()
        else:
            if User.objects.filter(phone=phone).exists():
                raise ValueError(f"Phone number {phone} is already used by another account.")

            user = User.objects.create_user(
                username=self._build_unique_username(email),
                email=email,
                password=password,
                role=role,
                phone=phone,
                name=name,
                is_active=True,
                linked_student=linked_student,
            )

        return user, password

    def patch(self, request, lead_id):
        # Find lead
        try:
            lead = Lead.objects.get(id=lead_id)
        except Lead.DoesNotExist:
            return Response(
                {
                    "success": False,
                    "message": "Lead not found."
                },
                status=status.HTTP_404_NOT_FOUND
            )
        # Validate input
        serializer = LeadStageUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {
                    "success": False,
                    "errors": serializer.errors
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        new_stage = serializer.validated_data["stage"]
        note = serializer.validated_data.get("note", "")
        
        old_stage = lead.current_stage

        # Handle conversion to student
        if new_stage == 'converted' and old_stage != 'converted':
            if not lead.email:
                return Response(
                    {
                        "success": False,
                        "message": "Lead email is required to create a student login account."
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            if not lead.phone_student:
                return Response(
                    {
                        "success": False,
                        "message": "Lead phone number is required to create a student login account."
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            if not lead.email_parent:
                return Response(
                    {
                        "success": False,
                        "message": "Parent email is required to create parent login account."
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            parent_phone = lead.phone_father or lead.phone_father_2
            if not parent_phone:
                return Response(
                    {
                        "success": False,
                        "message": "Parent phone is required to create parent login account."
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            try:
                student_name = f"{lead.first_name} {lead.surname}".strip() or lead.first_name
                student_user, student_password = self._create_or_update_user(
                    email=lead.email,
                    phone=lead.phone_student,
                    name=student_name,
                    role='student',
                    linked_student=None,
                )

                parent_name = lead.father_name.strip() if lead.father_name else f"Parent of {student_name}"
                parent_user, parent_password = self._create_or_update_user(
                    email=lead.email_parent,
                    phone=parent_phone,
                    name=parent_name,
                    role='parents',
                    linked_student=student_user,
                )

                try:
                    send_student_login_credentials(student_user, student_password)
                    send_parent_login_credentials(parent_user, student_user, parent_password)
                    logger.info(
                        f"Student and parent credentials sent for converted lead {lead.id} "
                        f"(student={student_user.email}, parent={parent_user.email})"
                    )
                except Exception as e:
                    logger.error(f"Failed to send credentials email for lead {lead.id}: {str(e)}")
                    # Continue even if email fails - users are still created

            except Exception as e:
                logger.error(f"Error creating student user for lead {lead.id}: {str(e)}")
                return Response(
                    {
                        "success": False,
                        "message": f"Error creating student account: {str(e)}"
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

        # Update lead current stage
        lead.current_stage = new_stage
        lead.save(update_fields=["current_stage", "updated_at"])

        # Create stage history
        LeadStage.objects.create(
            lead=lead,
            stage=new_stage,
            changed_by=request.user if request.user.is_authenticated else None,
            note=note
        )

        return Response(
            {
                "success": True,
                "message": "Lead status updated successfully." + (
                    " Student and parent accounts created, linked, and credentials sent."
                    if new_stage == 'converted' and old_stage != 'converted'
                    else ""
                ),
                "data": {
                    "lead_id": lead.id,
                    "current_stage": lead.current_stage,
                }
            },
            status=status.HTTP_200_OK
        )



class LeadDetailView(APIView):
    """
    GET    /leads/<id>/   — retrieve a single lead (full detail)
    PUT    /leads/<id>/   — full update
    PATCH  /leads/<id>/   — partial update
    DELETE /leads/<id>/   — soft-delete / hard-delete
    """

    def _get_lead(self, lead_id):
        try:
            return Lead.objects.get(id=lead_id)
        except Lead.DoesNotExist:
            return None

    # ── GET ────────────────────────────────────────────────────────────
    def get(self, request, lead_id):
        lead = self._get_lead(lead_id)
        if lead is None:
            return Response(
                {"success": False, "message": "Lead not found."},
                status=status.HTTP_404_NOT_FOUND
            )
        serializer = LeadDetailSerializer(lead)
        return Response(
            {"success": True, "data": serializer.data},
            status=status.HTTP_200_OK
        )

    # ── PUT / PATCH ───────────────────────────────────────────────
    def _update(self, request, lead_id, partial: bool):
        lead = self._get_lead(lead_id)
        if lead is None:
            return Response(
                {"success": False, "message": "Lead not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = LeadUpdateSerializer(lead, data=request.data, partial=partial)
        if not serializer.is_valid():
            logger.warning(
                f"Lead update validation failed — lead_id: {lead_id} | "
                f"errors: {serializer.errors}"
            )
            return Response(
                {
                    "success": False,
                    "message": "Please fix the errors below.",
                    "errors": serializer.errors
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer.save()
        return Response(
            {
                "success": True,
                "message": "Lead updated successfully.",
                "data": LeadDetailSerializer(lead).data
            },
            status=status.HTTP_200_OK
        )

    def put(self, request, lead_id):
        return self._update(request, lead_id, partial=False)

    def patch(self, request, lead_id):
        return self._update(request, lead_id, partial=True)

    # ── DELETE ───────────────────────────────────────────────────
    def delete(self, request, lead_id):
        lead = self._get_lead(lead_id)
        if lead is None:
            return Response(
                {"success": False, "message": "Lead not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        lead.delete()
        return Response(
            {"success": True, "message": f"Lead {lead_id} deleted successfully."},
            status=status.HTTP_200_OK
        )