from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from django.utils import timezone

from .models import Branch
from .serializers import (BranchListSerializer,BranchDetailSerializer,BranchCreateSerializer,BranchSummarySerializer,)

from django.db.models import Q
from rest_framework.filters import SearchFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend
from core.utils import apply_filters
from core.pagination import paginate_queryset

# ==========================================
# LIST + CREATE API
# ==========================================
class BranchListCreateAPIView(APIView):
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['is_active', 'city']
    search_fields = ['name', 'address', 'city', 'state']
    ordering_fields = '__all__'

    def get(self, request):

        branches = Branch.objects.filter(is_deleted=False)
        if getattr(request.user, 'organization', None):
            branches = branches.filter(organization=request.user.organization)
            
        is_active = request.GET.get("is_active")
        if is_active is not None:
            branches = branches.filter(is_active=str(is_active).lower() == 'true')
            
        branches = apply_filters(self, request, branches)
            
        return paginate_queryset(branches, request, BranchListSerializer)
    
    def post(self, request):
        serializer = BranchCreateSerializer(data=request.data)
        if serializer.is_valid():
            org = getattr(request.user, 'organization', None)
            serializer.save(organization=org)
            return Response({
                "success": True,
                "message": "Branch created successfully.",
                "data": serializer.data
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors,status=status.HTTP_400_BAD_REQUEST)


# ==========================================
# DETAIL + UPDATE + DELETE API
# ==========================================

class BranchDetailAPIView(APIView):
    def get_object(self, pk):
        try:
            qs = Branch.objects.all()
            if getattr(self.request.user, 'organization', None):
                qs = qs.filter(organization=self.request.user.organization)
            return qs.get(pk=pk)
        except Branch.DoesNotExist:
            return None
    def get(self, request, pk):
        branch = self.get_object(pk)
        if not branch:
            return Response(
                {
                    "message": "Branch not found"
                },
                status=status.HTTP_404_NOT_FOUND
            )
        serializer = BranchDetailSerializer(branch)

        return Response(serializer.data)

    def patch(self, request, pk):
        branch = self.get_object(pk)
        if not branch:
            return Response(
                {
                    "message": "Branch not found"
                },
                status=status.HTTP_404_NOT_FOUND
            )
        data = request.data.copy() if hasattr(request.data, 'copy') else dict(request.data)
        if 'logo' in data and isinstance(data.get('logo'), str):
            data.pop('logo')

        serializer = BranchCreateSerializer(branch,data=data,partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors,status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        branch = self.get_object(pk)
        if not branch:
            return Response(
                {
                    "message": "Branch not found"
                },
                status=status.HTTP_404_NOT_FOUND
            )
        branch.delete()
        return Response(
            {
                "message": "Branch deleted successfully"
            },
            status=status.HTTP_200_OK
        )


# ==========================================
# SUMMARY API
# ==========================================

class BranchSummaryAPIView(APIView):

    def get(self, request, pk):
        branch_qs = Branch.objects.all()
        if getattr(request.user, 'organization', None):
            branch_qs = branch_qs.filter(organization=request.user.organization)
        branch = branch_qs.filter(pk=pk).first()
        if not branch:
            return Response(
                {"message": "Branch not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        now = timezone.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # ── Lazy imports to avoid circular deps ──────────────────────────────
        from auth_user.models import User
        from leads.models import Lead
        from onboarding.models import Admission

        # ── Students ─────────────────────────────────────────────────────────
        student_qs = User.objects.filter(branch=branch, role='student')
        total_students = student_qs.count()
        active_students = student_qs.filter(is_active=True).count()

        # ── Staff (everyone except students & parents) ───────────────────────
        total_staff = (
            User.objects
            .filter(branch=branch)
            .exclude(role__in=['student', 'parents'])
            .count()
        )

        # ── Leads ────────────────────────────────────────────────────────────
        lead_qs = Lead.objects.filter(branch=branch)
        total_leads = lead_qs.count()
        leads_this_month = lead_qs.filter(created_at__gte=month_start).count()

        # ── Admissions this month (status = enrolled) ────────────────────────
        admissions_this_month = (
            Admission.objects
            .filter(branch=branch, submitted_at__gte=month_start, status='enrolled')
            .count()
        )

        # ── Fees / Exams / Attendance  (no models yet → 0) ──────────────────
        # TODO: wire when Fee, Exam, Attendance apps are created
        fee_collected_this_month = 0
        fee_pending = 0
        exams_this_month = 0
        attendance_avg_percent = 0.0

        data = {
            "total_students": total_students,
            "active_students": active_students,
            "total_staff": total_staff,
            "total_leads": total_leads,
            "leads_this_month": leads_this_month,
            "admissions_this_month": admissions_this_month,
            "fee_collected_this_month": fee_collected_this_month,
            "fee_pending": fee_pending,
            "exams_this_month": exams_this_month,
            "attendance_avg_percent": attendance_avg_percent,
        }
        serializer = BranchSummarySerializer(data)
        return Response(serializer.data)