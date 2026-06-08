import logging
from core.pagination import paginate_queryset

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.exceptions import ValidationError

from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.filters import SearchFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend
from core.utils import apply_filters
from core.email import send_email

from .serializers import get_lead_serializer, LeadStageUpdateSerializer, LeadListSerializer, LeadDetailSerializer, LeadUpdateSerializer
from .utils import LeadService
from .models import Lead, LeadStage, FORM_TYPE_CHOICES, STAGE_CHOICES, COURSE_TYPE_CHOICES, GROUP_MODULE_CHOICES, ATTEMPT_TYPE_CHOICES
from django.db.models import Q
import re
from rest_framework.permissions import AllowAny

FORM_TYPE_DISPLAY = dict(FORM_TYPE_CHOICES)
STAGE_DISPLAY = dict(STAGE_CHOICES)
COURSE_DISPLAY = dict(COURSE_TYPE_CHOICES)
GROUP_MODULE_DISPLAY = dict(GROUP_MODULE_CHOICES)
ATTEMPT_DISPLAY = dict(ATTEMPT_TYPE_CHOICES)

logger = logging.getLogger(__name__)


class LeadListView(APIView):
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['current_stage', 'course', 'form_type']
    search_fields = ['first_name', 'surname', 'email', 'phone_student']
    ordering_fields = '__all__'

    def get_permissions(self):
        if self.request.method == 'POST':
            return [AllowAny()]
        return [IsAuthenticated()]

    permission_classes=[AllowAny]

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
                    "form_type": form_type,
                    "form_type_display": FORM_TYPE_DISPLAY.get(form_type),
                    "valid_form_types": [
                        {"value": key, "display": label}
                        for key, label in FORM_TYPE_CHOICES
                    ],
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
                    "lead_id":             lead.id,
                    "form_type":           lead.form_type,
                    "form_type_display":   FORM_TYPE_DISPLAY.get(lead.form_type),
                    "course":              lead.course,
                    "course_display":      COURSE_DISPLAY.get(lead.course),
                    "group_module":        lead.group_module,
                    "group_module_display": GROUP_MODULE_DISPLAY.get(lead.group_module),
                    "batch_attempt":       lead.batch_attempt,
                    "batch_attempt_display": ATTEMPT_DISPLAY.get(lead.batch_attempt),
                    "name":                lead.first_name,
                    "stage":               lead.current_stage,
                    "stage_display":       STAGE_DISPLAY.get(lead.current_stage),
                }
            },
            status=status.HTTP_201_CREATED
        )

    def get(self, request):

        queryset = Lead.objects.all().order_by("-created_at")
        
        if getattr(request.user, 'organization', None):
            queryset = queryset.filter(branch__organization=request.user.organization)

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

        queryset = apply_filters(self, request, queryset)

        return paginate_queryset(queryset, request, LeadListSerializer)


class LeadStatusUpdateView(APIView):
    permission_classes=[AllowAny]
    def patch(self, request, lead_id):
        # Find lead
        try:
            queryset = Lead.objects.all()
            if getattr(request.user, 'organization', None):
                queryset = queryset.filter(branch__organization=request.user.organization)
            lead = queryset.get(id=lead_id)
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

        # ── Handle conversion: auto-create Admission record ──────────────────
        admission_created = False
        if new_stage == 'converted' and old_stage != 'converted':
            try:
                from onboarding.models import Admission
                from onboarding.utils import AdmissionService

                # Check if an admission already exists for this lead
                if not Admission.objects.filter(lead=lead).exists():
                    # Build admission data from lead fields
                    admission_data = {
                        'lead_id':          lead.id,
                        'first_name':       lead.first_name,
                        'surname':          lead.surname or '',
                        'father_name':      lead.father_name or '',
                        'mother_name':      '',
                        'dob':              None,
                        'category':         'gen',
                        'email':            lead.email or '',
                        'email_parent':     '',
                        'phone_student':    lead.phone_student or '',
                        'phone_student_2':  '',
                        'phone_father':     lead.phone_father or '',
                        'phone_father_2':   '',
                        'street':           lead.street or '',
                        'apartment':        lead.apartment or '',
                        'city':             lead.city or '',
                        'state':            lead.state or '',
                        'pincode':          '',
                        'country':          lead.country or 'India',
                        'course':           lead.course or 'cseet',
                        'group_module':     lead.group_module or 'full',
                        'batch_attempt':    lead.batch_attempt or 'june',
                        'location':         lead.location or '',
                        'qualification':    lead.qualification or 'appearing_12',
                        'reference':        lead.reference or 'none',
                        'consent':          True,
                        'tenth_medium':     lead.tenth_medium or 'cbse',
                        'tenth_school':     lead.tenth_school or '',
                        'tenth_coaching':   lead.tenth_coaching or '',
                        'tenth_percentage': lead.tenth_percentage or 0,
                        'tenth_percentile': lead.tenth_percentile or 0,
                        'twelfth_medium':   lead.twelfth_medium or 'cbse',
                        'twelfth_school':   lead.twelfth_school or '',
                        'twelfth_coaching': lead.twelfth_coaching or '',
                        'twelfth_percentage': lead.twelfth_percentage or 0,
                        'twelfth_percentile': lead.twelfth_percentile or 0,
                        'grad_university':  lead.grad_university or '',
                        'grad_college':     lead.grad_college or '',
                        'grad_last_sem':    lead.grad_last_sem or '',
                    }

                    # Auto-assign counsellor via round-robin
                    assigned_counsellor = AdmissionService.get_next_counsellor()

                    # Create Admission with status='approval_pending' (no credentials yet)
                    counsellor_name = assigned_counsellor.name if assigned_counsellor else 'Unassigned'
                    auto_note = f'Auto-created from converted lead #{lead.id}. Assigned to {counsellor_name} for review.'
                    
                    admission = Admission(
                        id=lead.id,
                        lead=lead,
                        branch=lead.branch,
                        status='approval_pending',
                        note=auto_note,
                        assigned_counsellor=assigned_counsellor,
                        **{k: v for k, v in admission_data.items() if k != 'lead_id'},
                    )
                    admission.save()

                    from onboarding.models import AdmissionStatusHistory
                    AdmissionStatusHistory.objects.create(
                        admission=admission,
                        status='approval_pending',
                        changed_by=request.user if request.user.is_authenticated else None,
                        note=auto_note,
                    )

                    admission_created = True
                    logger.info(
                        f"Admission {admission.id} auto-created from converted lead {lead.id}, "
                        f"assigned to counsellor: {counsellor_name}"
                    )
                    
                    if admission.email:
                        try:
                            admission_link = f"http://localhost:5173/insight/student/admission-form?id={lead.id}"
                            subject = "Complete Your Admission Process"
                            text_content = f"Hello {admission.first_name},\n\nWe are thrilled to welcome you! Your lead has been converted, and we are ready to proceed with your admission.\n\nPlease click the link below to complete your admission form and upload the necessary documents:\n\n{admission_link}\n\nIf you have any questions, feel free to reach out.\n\nBest Regards,\nInsight Institute Team"
                            
                            send_email(
                                to=admission.email,
                                subject=subject,
                                text=text_content,
                                template=None,
                                template_context={},
                                organization=admission.branch.organization if getattr(admission, 'branch', None) else None,
                            )
                            logger.info(f"Admission form email sent to {admission.email}")
                        except Exception as e:
                            logger.error(f"Failed to send admission form email to {admission.email}: {e}")

            except Exception as e:
                logger.error(f"Error creating admission for lead {lead.id}: {str(e)}")
                return Response(
                    {
                        "success": False,
                        "message": f"Error creating admission record: {str(e)}"
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

        # Update lead current stage and note
        lead.current_stage = new_stage
        lead.note = note
        lead.save(update_fields=["current_stage", "note", "updated_at"])

        # Create stage history
        LeadStage.objects.create(
            lead=lead,
            stage=new_stage,
            changed_by=request.user if request.user.is_authenticated else None,
            note=note
        )

        message = "Lead status updated successfully."
        response_data = {
            "lead_id": lead.id,
            "current_stage": lead.current_stage,
            "note": lead.note,
        }

        if admission_created:
            message += " Admission record created and assigned for counsellor review."
            counsellor_info = None
            if assigned_counsellor:
                counsellor_info = {
                    "id":    str(assigned_counsellor.id),
                    "name":  assigned_counsellor.name,
                    "email": assigned_counsellor.email,
                }
            response_data["admission"] = {
                "admission_id": admission.id,
                "status": admission.status,
                "assigned_counsellor": counsellor_info,
            }

        return Response(
            {
                "success": True,
                "message": message,
                "data": response_data,
            },
            status=status.HTTP_200_OK
        )



class LeadDetailView(APIView):
    permission_classes=[AllowAny]

    """
    GET    /leads/<id>/   — retrieve a single lead (full detail)
    PUT    /leads/<id>/   — full update
    PATCH  /leads/<id>/   — partial update
    DELETE /leads/<id>/   — soft-delete / hard-delete
    """

    def _get_lead(self, request, lead_id):
        try:
            queryset = Lead.objects.all()
            if getattr(request.user, 'organization', None):
                queryset = queryset.filter(branch__organization=request.user.organization)
            return queryset.get(id=lead_id)
        except Lead.DoesNotExist:
            return None

    # ── GET ────────────────────────────────────────────────────────────
    def get(self, request, lead_id):
        lead = self._get_lead(request, lead_id)
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
        lead = self._get_lead(request, lead_id)
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
        lead = self._get_lead(request, lead_id)
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