import logging
from core.pagination import paginate_queryset

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.permissions import AllowAny
from django_filters.rest_framework import DjangoFilterBackend
from core.utils import apply_filters

from django.db.models import Sum, Count, Q
from django.utils import timezone

from .models import (
    FeeStructure, StudentFee,
    InstallmentPlan, InstallmentItem,
    Payment, Refund, BankAccount,
    FEE_STATUS_CHOICES,
)
from .serializers import (
    FeeStructureListSerializer, FeeStructureDetailSerializer, FeeStructureCreateUpdateSerializer,
    StudentFeeListSerializer, StudentFeeDetailSerializer, StudentFeeCreateUpdateSerializer,
    InstallmentPlanListSerializer, InstallmentPlanCreateSerializer, InstallmentPlanApproveSerializer,
    InstallmentItemSerializer,
    PaymentListSerializer, PaymentDetailSerializer, PaymentCreateSerializer, PaymentVerifySerializer,
    RefundListSerializer, RefundCreateSerializer,
    BankAccountListSerializer, BankAccountCreateUpdateSerializer,
    FeeReportSerializer,
)
from .utils import (
    update_student_fee_status, mark_installment_paid, get_installment_plan_status,
    get_recipient_emails,
)
from .services import send_payment_receipt

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
#  Fee Structure Views
# ═══════════════════════════════════════════════════════════════════════════════

class FeeStructureListView(APIView):
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['course', 'batch', 'level', 'syllabus', 'is_active']
    search_fields = ['name']
    ordering_fields = '__all__'

    def get_permissions(self):
        if self.request.method == 'GET':
            return [AllowAny()]
        return super().get_permissions()

    def get(self, request):
        queryset = FeeStructure.objects.select_related('course', 'batch', 'level', 'syllabus').prefetch_related('student_fees', 'syllabus__modules').all()
        if getattr(request.user, 'organization', None):
            queryset = queryset.filter(
                Q(course__organization=request.user.organization) |
                Q(batch__organization=request.user.organization)
            )

        course_id = request.GET.get('course_id')
        batch_id = request.GET.get('batch_id')
        level_id = request.GET.get('level_id') or request.GET.get('level')
        syllabus_id = request.GET.get('syllabus_id') or request.GET.get('syllabus')
        is_active = request.GET.get('is_active')

        if course_id:
            queryset = queryset.filter(course_id=course_id)
        if batch_id:
            queryset = queryset.filter(batch_id=batch_id)
        if level_id:
            queryset = queryset.filter(level_id=level_id)
        if syllabus_id:
            queryset = queryset.filter(syllabus_id=syllabus_id)
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')

        queryset = apply_filters(self, request, queryset)

        return paginate_queryset(queryset, request, FeeStructureListSerializer)

    def post(self, request):
        serializer = FeeStructureCreateUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {'success': False, 'message': 'Please fix the errors below.', 'errors': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
        fee_structure = serializer.save(
            created_by=request.user if request.user.is_authenticated else None
        )
        return Response(
            {'success': True, 'message': 'Fee structure created.',
             'data': FeeStructureDetailSerializer(fee_structure).data},
            status=status.HTTP_201_CREATED,
        )


class FeeStructureDetailView(APIView):

    def get_permissions(self):
        if self.request.method == 'GET':
            return [AllowAny()]
        return super().get_permissions()

    def _get(self, request, pk):
        try:
            queryset = FeeStructure.objects.select_related('course', 'batch', 'level', 'syllabus').prefetch_related('syllabus__modules').all()
            if getattr(request.user, 'organization', None):
                queryset = queryset.filter(
                    Q(course__organization=request.user.organization) |
                    Q(batch__organization=request.user.organization)
                )
            return queryset.get(pk=pk)
        except FeeStructure.DoesNotExist:
            return None

    def get(self, request, pk):
        obj = self._get(request, pk)
        if obj is None:
            return Response({'success': False, 'message': 'Fee structure not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response({'success': True, 'data': FeeStructureDetailSerializer(obj).data})

    def patch(self, request, pk):
        obj = self._get(request, pk)
        if obj is None:
            return Response({'success': False, 'message': 'Fee structure not found.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = FeeStructureCreateUpdateSerializer(obj, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response({'success': False, 'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
        serializer.save()
        return Response({'success': True, 'message': 'Fee structure updated.',
                         'data': FeeStructureDetailSerializer(obj).data})

    def delete(self, request, pk):
        obj = self._get(request, pk)
        if obj is None:
            return Response({'success': False, 'message': 'Fee structure not found.'}, status=status.HTTP_404_NOT_FOUND)
        obj.delete()
        return Response({'success': True, 'message': 'Fee structure deleted.'})


# ═══════════════════════════════════════════════════════════════════════════════
#  Student Fee Views
# ═══════════════════════════════════════════════════════════════════════════════

class StudentFeeListView(APIView):
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['student', 'status', 'fee_structure']
    search_fields = ['student__first_name', 'student__surname', 'fee_structure__name']
    ordering_fields = '__all__'

    def get(self, request):
        # Optimized: prefetch_related for reverse relations
        queryset = StudentFee.objects.select_related('student', 'fee_structure').prefetch_related('payments', 'installment_plans').all()
        if getattr(request.user, 'organization', None):
            queryset = queryset.filter(student__branch__organization=request.user.organization)

        student_id = request.GET.get('student_id')
        status_filter = request.GET.get('status')
        fee_structure_id = request.GET.get('fee_structure_id')
        branch_id = request.GET.get("branch_id")
        batch_id = request.GET.get("batch_id")
        date_from = request.GET.get("date_from")
        date_to = request.GET.get("date_to")

        if student_id:
            queryset = queryset.filter(student_id=student_id)
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        if fee_structure_id:
            queryset = queryset.filter(fee_structure_id=fee_structure_id)
        if branch_id:
            queryset = queryset.filter(student__branch_id=branch_id)
        if batch_id:
            queryset = queryset.filter(student__batch_id=batch_id)
        if date_from or date_to:
            date_q = Q()
            item_q = Q()
            if date_from:
                date_q &= Q(due_date__gte=date_from[:10])
                item_q &= Q(installment_plans__items__due_date__gte=date_from[:10])
            if date_to:
                date_q &= Q(due_date__lte=date_to[:10])
                item_q &= Q(installment_plans__items__due_date__lte=date_to[:10])
            queryset = queryset.filter(date_q | item_q).distinct()

        queryset = apply_filters(self, request, queryset)

        return paginate_queryset(queryset, request, StudentFeeListSerializer)

    def post(self, request):
        serializer = StudentFeeCreateUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {'success': False, 'message': 'Please fix the errors below.', 'errors': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
        student_fee = serializer.save()
        return Response(
            {'success': True, 'message': 'Student fee assigned.',
             'data': StudentFeeDetailSerializer(student_fee).data},
            status=status.HTTP_201_CREATED,
        )


class StudentFeeDetailView(APIView):

    def _get(self, request, pk):
        try:
            queryset = StudentFee.objects.select_related('student', 'fee_structure').all()
            if getattr(request.user, 'organization', None):
                queryset = queryset.filter(student__branch__organization=request.user.organization)
            return queryset.get(pk=pk)
        except StudentFee.DoesNotExist:
            return None

    def get(self, request, pk):
        obj = self._get(request, pk)
        if obj is None:
            return Response({'success': False, 'message': 'Student fee not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response({'success': True, 'data': StudentFeeDetailSerializer(obj).data})

    def patch(self, request, pk):
        obj = self._get(request, pk)
        if obj is None:
            return Response({'success': False, 'message': 'Student fee not found.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = StudentFeeCreateUpdateSerializer(obj, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response({'success': False, 'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
        serializer.save()
        update_student_fee_status(obj.id)  # recalculate status
        return Response({'success': True, 'message': 'Student fee updated.',
                         'data': StudentFeeDetailSerializer(obj).data})

    def delete(self, request, pk):
        obj = self._get(request, pk)
        if obj is None:
            return Response({'success': False, 'message': 'Student fee not found.'}, status=status.HTTP_404_NOT_FOUND)
        obj.delete()
        return Response({'success': True, 'message': 'Student fee deleted.'})


class StudentFeeByStudentView(APIView):
    """GET /api/v1/fees/student/<student_id>/ — full fee overview for a student."""

    def get(self, request, student_id):
        from students.models import Student
        try:
            queryset = Student.objects.all()
            if getattr(request.user, 'organization', None):
                queryset = queryset.filter(branch__organization=request.user.organization)
            student = queryset.get(id=student_id)
        except Student.DoesNotExist:
            return Response({'success': False, 'message': 'Student not found.'}, status=status.HTTP_404_NOT_FOUND)

        student_fees = StudentFee.objects.select_related(
            'fee_structure'
        ).filter(student=student).order_by('-created_at')

        # Summary
        total_billed = student_fees.aggregate(
            total=Sum('total_amount')
        )['total'] or 0
        total_discount = student_fees.aggregate(
            total=Sum('discount')
        )['total'] or 0
        total_paid = student_fees.aggregate(
            total=Sum('amount_paid')
        )['total'] or 0

        serializer = StudentFeeListSerializer(student_fees, many=True)
        return Response({
            'success': True,
            'data': {
                'student_id': str(student.id),
                'student_name': student.full_name,
                'summary': {
                    'total_billed': total_billed,
                    'total_discount': total_discount,
                    'total_paid': total_paid,
                    'total_due': total_billed - total_discount - total_paid,
                },
                'fees': serializer.data,
            },
        })


# ═══════════════════════════════════════════════════════════════════════════════
#  Installment Plan Views
# ═══════════════════════════════════════════════════════════════════════════════

class InstallmentPlanListView(APIView):
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['student_fee', 'status']
    search_fields = ['student_fee__student__first_name', 'student_fee__student__surname']
    ordering_fields = '__all__'

    def get(self, request):
        queryset = InstallmentPlan.objects.select_related(
            'student_fee__student', 'student_fee__fee_structure'
        ).prefetch_related('items').all()
        if getattr(request.user, 'organization', None):
            queryset = queryset.filter(student_fee__student__branch__organization=request.user.organization)

        student_fee_id = request.GET.get('student_fee_id')
        plan_status = request.GET.get('status')

        if student_fee_id:
            queryset = queryset.filter(student_fee_id=student_fee_id)
        if plan_status:
            queryset = queryset.filter(status=plan_status)

        queryset = apply_filters(self, request, queryset)

        return paginate_queryset(queryset, request, InstallmentPlanListSerializer)


class InstallmentPlanCreateView(APIView):

    def post(self, request):
        serializer = InstallmentPlanCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {'success': False, 'message': 'Please fix the errors below.', 'errors': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = serializer.validated_data
        student_fee_id = data['student_fee_id']
        items_data = data['items']

        try:
            student_fee = StudentFee.objects.get(id=student_fee_id)
        except StudentFee.DoesNotExist:
            return Response({'success': False, 'message': 'Student fee not found.'}, status=status.HTTP_404_NOT_FOUND)

        # Determine initial status using utility (CSEET >2 or others >4 items → pending_approval).
        # Uses level.name (replaces deprecated course_type).
        fee_structure = student_fee.fee_structure
        level_name = (
            getattr(getattr(fee_structure, 'level', None), 'name', '')
            or getattr(getattr(fee_structure, 'course', None), 'name', '')
            or ''
        )
        num_installments = len(items_data)
        initial_status = get_installment_plan_status(level_name, num_installments)

        approved_by = None
        approved_at = None
        if initial_status == 'approved':
            # approved_by = request.user if request.user.is_authenticated else None
            approved_at = timezone.now()

        # Validate total amounts match
        items_total = sum(float(item['amount']) for item in items_data)
        if abs(items_total - float(student_fee.amount_due)) > 0.01:
            return Response(
                {'success': False,
                 'message': f'Sum of installment items (₹{items_total}) must equal amount due (₹{student_fee.amount_due}).'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        plan = InstallmentPlan.objects.create(
            student_fee=student_fee,
            created_by=request.user if request.user.is_authenticated else None,
            status=initial_status,
            approved_by=approved_by,
            approved_at=approved_at,
        )
        for item in items_data:
            InstallmentItem.objects.create(
                plan=plan,
                amount=item['amount'],
                due_date=item['due_date'],
            )

        message = (
            'Installment plan created and approved automatically.'
            if initial_status == 'approved'
            else 'Installment plan created (pending approval).'
        )
        return Response(
            {'success': True, 'message': message,
             'data': InstallmentPlanListSerializer(plan).data},
            status=status.HTTP_201_CREATED,
        )


class InstallmentPlanApproveView(APIView):

    def post(self, request, pk):
        try:
            queryset = InstallmentPlan.objects.all()
            if getattr(request.user, 'organization', None):
                queryset = queryset.filter(student_fee__student__branch__organization=request.user.organization)
            plan = queryset.get(pk=pk)
        except InstallmentPlan.DoesNotExist:
            return Response({'success': False, 'message': 'Installment plan not found.'}, status=status.HTTP_404_NOT_FOUND)

        if plan.status != 'pending_approval':
            return Response(
                {'success': False, 'message': f'Cannot approve plan in {plan.status} status.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = InstallmentPlanApproveSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({'success': False, 'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

        new_status = serializer.validated_data['status']
        plan.status = new_status

        if new_status == 'approved':
            plan.approved_by = request.user if request.user.is_authenticated else None
            plan.approved_at = timezone.now()
        elif new_status == 'rejected':
            plan.rejection_reason = serializer.validated_data.get('rejection_reason', '')

        plan.save()
        return Response(
            {'success': True, 'message': f'Installment plan {new_status}.',
             'data': InstallmentPlanListSerializer(plan).data},
        )


# ═══════════════════════════════════════════════════════════════════════════════
#  Payment Views
# ═══════════════════════════════════════════════════════════════════════════════

class PaymentListView(APIView):
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['student', 'admission', 'status', 'payment_mode']
    search_fields = ['student__first_name', 'student__surname', 'admission__first_name', 'admission__surname', 'transaction_ref', 'receipt_number']
    ordering_fields = '__all__'

    def get(self, request):
        queryset = Payment.objects.select_related(
            'student', 'student_fee', 'admission', 'admission__branch', 'admission__fee_structure'
        ).prefetch_related('refunds').all()

        if getattr(request.user, 'organization', None):
            queryset = queryset.filter(
                Q(student__branch__organization=request.user.organization) |
                Q(admission__branch__organization=request.user.organization)
            )

        student_id = request.GET.get('student_id')
        admission_id = request.GET.get('admission_id') or request.GET.get('admission')
        payment_status = request.GET.get('status')
        payment_mode = request.GET.get('payment_mode')
        date_from = request.GET.get('date_from')
        date_to = request.GET.get('date_to')

        if student_id:
            queryset = queryset.filter(student_id=student_id)
        if admission_id:
            queryset = queryset.filter(admission_id=admission_id)
        if payment_status:
            queryset = queryset.filter(status=payment_status)
        if payment_mode:
            queryset = queryset.filter(payment_mode=payment_mode)
        if date_from:
            queryset = queryset.filter(payment_date__gte=date_from[:10])
        if date_to:
            queryset = queryset.filter(payment_date__lte=date_to[:10])

        queryset = apply_filters(self, request, queryset)

        return paginate_queryset(queryset, request, PaymentListSerializer)

    def post(self, request):
        serializer = PaymentCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {'success': False, 'message': 'Please fix the errors below.', 'errors': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        payment = serializer.save(
            recorded_by=request.user if request.user.is_authenticated else None,
        )

        # Update StudentFee paid amount
        update_student_fee_status(payment.student_fee_id)

        # If linked to installment item, check if paid
        if payment.installment_item_id:
            try:
                mark_installment_paid(payment.installment_item_id)
            except Exception as e:
                logger.error(f'Failed to mark installment paid: {e}')

        # Notify admins if approval pending
        if payment.status == 'approval_pending':
            from core.utils import notify_users_by_role
            notify_users_by_role(
                roles=['super_admin', 'branch_manager'],
                title='Payment Approval Required',
                body=f"A new payment of ₹{payment.amount} by {payment.student.first_name} requires approval.",
                organization=payment.student.branch.organization if getattr(payment.student, 'branch', None) else None,
                branch=payment.student.branch if getattr(payment.student, 'branch', None) else None,
                email_subject='Pending Payment Approval'
            )
            admission = getattr(payment.student, 'admission', None)
            if admission:
                admission.add_payment_history_entry('payment_approval_pending', {
                    'payment_choice': payment.payment_mode,
                    'payment_type': admission.payment_type,
                    'payment_type_display': admission.get_payment_type_display(),
                    'amount': float(payment.amount),
                    'total_fees': float(admission.total_fees),
                    'remaining_fees': float(admission.remaining_fees),
                    'transaction_id': payment.transaction_ref,
                    'receipt_number': payment.receipt_number,
                    'status': 'approval_pending',
                    'date': timezone.now().date().isoformat(),
                    'note': f"Manual {payment.payment_mode} payment recorded in Student Fees. Pending approval.",
                })

        return Response(
            {'success': True, 'message': 'Payment recorded.',
             'data': PaymentDetailSerializer(payment).data},
            status=status.HTTP_201_CREATED,
        )


class PaymentDetailView(APIView):

    def _get(self, request, pk):
        try:
            queryset = Payment.objects.select_related('student', 'student_fee', 'admission').all()
            if getattr(request.user, 'organization', None):
                queryset = queryset.filter(
                    Q(student__branch__organization=request.user.organization) |
                    Q(admission__branch__organization=request.user.organization)
                )
            return queryset.get(pk=pk)
        except Payment.DoesNotExist:
            return None

    def get(self, request, pk):
        obj = self._get(request, pk)
        if obj is None:
            return Response({'success': False, 'message': 'Payment not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response({'success': True, 'data': PaymentDetailSerializer(obj).data})


class PaymentVerifyView(APIView):

    def post(self, request, pk):
        role = getattr(request.user, 'role', '') if (request.user and request.user.is_authenticated) else ''
        is_superuser = getattr(request.user, 'is_superuser', False) if request.user else False
        if role not in ('accountant', 'super_admin') and not is_superuser:
            return Response(
                {
                    'success': False,
                    'message': 'Permission denied. Only Accountant or Super Admin can verify payments.',
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            queryset = Payment.objects.select_related(
                'installment_item__plan', 'student_fee', 'student', 'admission', 'admission__branch'
            ).all()
            if getattr(request.user, 'organization', None):
                queryset = queryset.filter(
                    Q(student__branch__organization=request.user.organization) |
                    Q(admission__branch__organization=request.user.organization)
                )
            payment = queryset.get(pk=pk)
        except Payment.DoesNotExist:
            return Response({'success': False, 'message': 'Payment not found.'}, status=status.HTTP_400_BAD_REQUEST)

        if payment.status not in ('approval_pending', 'level_1_approved'):
            return Response(
                {'success': False, 'message': f'Payment is already {payment.status}.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        admission = payment.admission or (
            payment.student.admission if getattr(payment, 'student', None) and hasattr(payment.student, 'admission') else None
        )
        is_level1_role = (role == 'accountant' and not is_superuser)

        if admission and is_level1_role and payment.status == 'level_1_approved':
            return Response(
                {
                    'success': False,
                    'message': 'Level 1 approval is already completed by Accountant. Pending Level 2 (final) approval by Super Admin.',
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Prevent approving/verifying payments linked to pending_approval installment plans.
        if payment.installment_item and payment.installment_item.plan.status == 'pending_approval':
            plan = payment.installment_item.plan
            return Response(
                {
                    'success': False,
                    'message': 'Cannot approve/verify this payment before the associated InstallmentPlan is approved.',
                    'errors': {'installment_plan': f'Plan {plan.id} is pending approval (approved_by not set).'}
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = PaymentVerifySerializer(data=request.data)
        if not serializer.is_valid():
            return Response({'success': False, 'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

        new_status = serializer.validated_data['status']
        note = serializer.validated_data.get('note', '')

        proof_url = None
        if payment.payment_proof:
            try:
                proof_url = request.build_absolute_uri(payment.payment_proof.url) if request else payment.payment_proof.url
            except Exception:
                proof_url = str(payment.payment_proof)

        verifier_name = (
            getattr(request.user, 'name', None) or getattr(request.user, 'email', None) or getattr(request.user, 'username', None)
            if (request.user and request.user.is_authenticated)
            else 'Admin/Accountant'
        )

        if new_status == 'verified':
            if admission and is_level1_role:
                # ── LEVEL 1 APPROVAL (Accountant) ─────────────────────────────
                payment.status = 'level_1_approved'
                payment.verified_by = request.user if request.user.is_authenticated else None
                payment.verified_at = timezone.now()
                payment.save(update_fields=['status', 'verified_by', 'verified_at'])

                from onboarding.utils import AdmissionService
                level1_note = note or 'Level 1 payment approval completed by Accountant via Payment Tab.'
                if admission.status in ('approval_pending', 'payment_submitted', 'payment_pending'):
                    AdmissionService.update_status(
                        admission=admission,
                        new_status='approved',
                        note=level1_note,
                        user=request.user,
                    )

                admission.add_payment_history_entry('payment_verified', {
                    'payment_choice': payment.payment_mode,
                    'payment_type': getattr(admission, 'payment_type', 'full'),
                    'payment_type_display': admission.get_payment_type_display() if hasattr(admission, 'get_payment_type_display') else '',
                    'amount': float(payment.amount),
                    'total_fees': float(getattr(admission, 'total_fees', 0) or 0),
                    'remaining_fees': float(getattr(admission, 'remaining_fees', 0) or 0),
                    'transaction_id': payment.transaction_ref,
                    'receipt_number': payment.receipt_number,
                    'status': 'level_1_approved',
                    'level': 1,
                    'approver_role': 'accountant',
                    'verified_by': verifier_name,
                    'verified_at': timezone.now().isoformat(),
                    'date': timezone.now().date().isoformat(),
                    'payment_screenshot': proof_url,
                    'payment_proof': proof_url,
                    'note': level1_note,
                })

                # Dispatch Level 2 WhatsApp notification to Super Admins
                try:
                    from onboarding.notifications import send_payment_verification_whatsapp
                    send_payment_verification_whatsapp(admission, level=2)
                except Exception as exc:
                    logger.error(f"Failed to dispatch Level 2 WhatsApp: {exc}")

                # Notify Super Admins via in-app/email
                try:
                    from core.utils import notify_users_by_role
                    notify_users_by_role(
                        roles=['super_admin'],
                        title='Admission Payment Ready for Final Approval',
                        body=f"Payment for admission #{admission.id} ({admission.first_name} {admission.surname}) was verified by Accountant and requires Super Admin final approval.",
                        organization=admission.branch.organization if getattr(admission, 'branch', None) else None,
                        branch=admission.branch if getattr(admission, 'branch', None) else None,
                        email_subject=f'Final Approval Required: Admission #{admission.id}',
                    )
                except Exception as exc:
                    logger.error(f"Failed to notify super_admin: {exc}")

                return Response({
                    'success': True,
                    'message': 'Level 1 payment approval completed by Accountant. Pending Level 2 (final) approval by Super Admin.',
                    'data': PaymentDetailSerializer(payment).data,
                }, status=status.HTTP_200_OK)

            else:
                # ── LEVEL 2 (FINAL) APPROVAL (Super Admin) ────────────────────
                payment.status = 'verified'
                payment.verified_by = request.user if request.user.is_authenticated else None
                payment.verified_at = timezone.now()
                payment.save(update_fields=['status', 'verified_by', 'verified_at'])

                if admission:
                    from onboarding.utils import AdmissionService
                    final_note = note or 'Level 2 final payment approval completed by Super Admin via Payment Tab.'
                    if admission.status != 'enrolled':
                        AdmissionService.update_status(
                            admission=admission,
                            new_status='enrolled',
                            note=final_note,
                            user=request.user,
                        )

                        from auth_user.models import User
                        student_user = User.objects.filter(
                            email__iexact=admission.email, role='student'
                        ).first()

                        if student_user and not payment.student:
                            try:
                                from students.utils import StudentService
                                student = StudentService.create_from_admission(
                                    admission=admission,
                                    user=student_user,
                                    acting_user=request.user,
                                )
                                payment.student = student
                                payment.save(update_fields=['student'])
                            except Exception as exc:
                                logger.error(f"Failed to auto-create student from admission in PaymentVerifyView: {exc}")

                    admission.add_payment_history_entry('payment_approved', {
                        'payment_choice': payment.payment_mode,
                        'payment_type': getattr(admission, 'payment_type', 'full'),
                        'payment_type_display': admission.get_payment_type_display() if hasattr(admission, 'get_payment_type_display') else '',
                        'amount': float(payment.amount),
                        'total_fees': float(getattr(admission, 'total_fees', 0) or 0),
                        'remaining_fees': float(getattr(admission, 'remaining_fees', 0) or 0),
                        'transaction_id': payment.transaction_ref,
                        'receipt_number': payment.receipt_number,
                        'status': 'verified',
                        'level': 2,
                        'approver_role': 'super_admin',
                        'verified_by': verifier_name,
                        'verified_at': timezone.now().isoformat(),
                        'date': timezone.now().date().isoformat(),
                        'payment_screenshot': proof_url,
                        'payment_proof': proof_url,
                        'note': final_note,
                    })

                # Recalculate student fee status if student_fee exists
                if payment.student_fee_id:
                    update_student_fee_status(payment.student_fee_id)

                # If linked to installment item, check if paid
                if payment.installment_item_id:
                    try:
                        mark_installment_paid(payment.installment_item_id)
                    except Exception as e:
                        logger.error(f'Failed to mark installment paid: {e}')

                send_payment_receipt(payment)

                return Response({
                    'success': True,
                    'message': 'Payment verified and approved successfully.',
                    'data': PaymentDetailSerializer(payment).data,
                }, status=status.HTTP_200_OK)

        elif new_status == 'rejected':
            payment.status = 'rejected'
            payment.note = note
            payment.verified_by = request.user if request.user.is_authenticated else None
            payment.verified_at = timezone.now()
            payment.save(update_fields=['status', 'note', 'verified_by', 'verified_at'])

            if admission:
                from onboarding.utils import AdmissionService
                AdmissionService.update_status(
                    admission=admission,
                    new_status='rejected',
                    note=note or 'Payment rejected via Payment Tab.',
                    user=request.user,
                )
                admission.add_payment_history_entry('payment_rejected', {
                    'payment_choice': payment.payment_mode,
                    'payment_type': getattr(admission, 'payment_type', 'full'),
                    'payment_type_display': admission.get_payment_type_display() if hasattr(admission, 'get_payment_type_display') else '',
                    'amount': float(payment.amount),
                    'total_fees': float(getattr(admission, 'total_fees', 0) or 0),
                    'remaining_fees': float(getattr(admission, 'remaining_fees', 0) or 0),
                    'transaction_id': payment.transaction_ref,
                    'receipt_number': payment.receipt_number,
                    'status': 'rejected',
                    'rejected_by': verifier_name,
                    'date': timezone.now().date().isoformat(),
                    'payment_screenshot': proof_url,
                    'payment_proof': proof_url,
                    'note': payment.note or 'Payment rejected in Student Fees.',
                })

            recipients = []
            if payment.student:
                recipients = get_recipient_emails(payment.student)
            elif payment.admission and getattr(payment.admission, 'email', None):
                recipients = [payment.admission.email]

            student_name = (
                getattr(payment.student, 'first_name', None) or
                (payment.admission.first_name if payment.admission else 'Student')
            )
            amount_str = f"{float(payment.amount):,.2f}"
            rejection_reason = payment.note if getattr(payment, 'note', None) else 'No reason provided'

            if recipients:
                from core.sender import send_email
                subject = f"Payment Rejected - {payment.transaction_ref or payment.id}"
                text_body = (
                    f"Dear {student_name},\n\n"
                    f"Unfortunately, your payment of ₹{payment.amount} has been rejected.\n\n"
                )
                if getattr(payment, 'note', None):
                    text_body += f"Reason: {payment.note}\n\n"
                text_body += "Please contact the administration for more details.\n\nInsight Institute of Professional Studies"

                template_context = {
                    'student_name': student_name,
                    'amount': payment.amount,
                    'reason': rejection_reason,
                    'primary_color': '#ed7c31',
                    'org_name': 'Insight Institute of Professional Studies',
                }

                for recipient in recipients:
                    try:
                        send_email(
                            to=recipient,
                            subject=subject,
                            text=text_body,
                            template="emails/payment_rejected.html",
                            template_context=template_context,
                        )
                        logger.info(f"Rejection email (with HTML template) sent to {recipient}")
                    except Exception as e:
                        logger.error(f"Failed to send rejection email to {recipient}: {e}")

            # WhatsApp: notify student + parent phones
            try:
                from chat.notifications import send_whatsapp_with_fallback
                wa_fallback = (
                    f"Dear {student_name},\n\n"
                    f"Unfortunately your payment of ₹{amount_str} has been rejected.\n"
                    f"Reason: {rejection_reason}\n\n"
                    f"Please contact administration immediately for resolution."
                )
                wa_phones = set()
                if payment.admission:
                    if getattr(payment.admission, 'phone_student', None):
                        wa_phones.add(payment.admission.phone_student)
                    if getattr(payment.admission, 'phone_father', None):
                        wa_phones.add(payment.admission.phone_father)
                if payment.student:
                    if getattr(payment.student, 'phone_student', None):
                        wa_phones.add(payment.student.phone_student)
                    if getattr(payment.student, 'phone_father', None):
                        wa_phones.add(payment.student.phone_father)
                    student_user = getattr(payment.student, 'user', None)
                    if student_user and getattr(student_user, 'phone', None):
                        wa_phones.add(student_user.phone)

                for phone in filter(None, wa_phones):
                    try:
                        send_whatsapp_with_fallback(
                            to=phone,
                            template_name="payment_rejected_",
                            language_code="en",
                            components=[{
                                "type": "body",
                                "parameters": [
                                    {"type": "text", "text": student_name},
                                    {"type": "text", "text": amount_str},
                                    {"type": "text", "text": rejection_reason},
                                ]
                            }],
                            fallback_body=wa_fallback,
                        )
                        logger.info(f"[Payment Rejected] WhatsApp sent to {phone}")
                    except Exception as wa_err:
                        logger.error(f"[Payment Rejected] WhatsApp to {phone} failed: {wa_err}")
            except Exception as wa_import_err:
                logger.error(f"[Payment Rejected] WhatsApp block failed: {wa_import_err}")

            return Response(
                {
                    'success': True,
                    'message': 'Payment rejected successfully.',
                    'data': PaymentDetailSerializer(payment).data,
                },
                status=status.HTTP_200_OK,
            )

        return Response(
            {'success': True, 'message': f'Payment {new_status}.',
             'data': PaymentDetailSerializer(payment).data},
        )


# ═══════════════════════════════════════════════════════════════════════════════
#  Refund Views
# ═══════════════════════════════════════════════════════════════════════════════

class RefundListView(APIView):
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['status', 'payment']
    search_fields = ['payment__receipt_number', 'reason']
    ordering_fields = '__all__'

    def get(self, request):
        queryset = Refund.objects.select_related('payment').all()
        if getattr(request.user, 'organization', None):
            queryset = queryset.filter(payment__student__branch__organization=request.user.organization)
        refund_status = request.GET.get('status')
        if refund_status:
            queryset = queryset.filter(status=refund_status)

        queryset = apply_filters(self, request, queryset)

        return paginate_queryset(queryset, request, RefundListSerializer)


def trigger_razorpay_refund(refund):
    """
    Auto-trigger Razorpay refund if payment was made online.
    Returns a tuple (rp_refund_id, rp_error).
    """
    rp_refund_id = None
    rp_error     = None
    transaction_ref = refund.payment.transaction_ref or ''
    if transaction_ref.startswith('pay_'):
        try:
            from .razorpay_service import create_refund as rp_create_refund
            rp_result = rp_create_refund(
                payment_id=transaction_ref,
                amount=float(refund.amount),
                reason=refund.reason or f'Refund for receipt {refund.payment.receipt_number}',
            )
            if rp_result.get('success'):
                rp_refund_id = rp_result['data'].get('id', '')
                logger.info(
                    f"[Refund] Razorpay refund {rp_refund_id} initiated "
                    f"for local Refund {refund.id} / Payment {refund.payment.id}"
                )
            else:
                rp_error = rp_result.get('error', 'Unknown Razorpay error')
                logger.error(f"[Refund] Razorpay refund failed for Payment {refund.payment.id}: {rp_error}")
        except Exception as exc:
            rp_error = str(exc)
            logger.error(f"[Refund] Razorpay refund exception for Payment {refund.payment.id}: {exc}")
    
    return rp_refund_id, rp_error

def send_refund_notifications(refund, rp_refund_id):
    """Send refund confirmation via email + WhatsApp to the student (and parent)."""
    from core.sender import send_email
    from django.utils import timezone

    payment      = refund.payment
    student      = payment.student
    refund_date  = timezone.localtime().strftime('%d %b, %Y')
    student_name = getattr(student, 'full_name', '') or str(student)
    student_user = getattr(student, 'user', None)
    org          = getattr(student_user, 'organization', None) if student_user else None

    amount_fmt = f"{float(refund.amount):,.2f}"
    subject    = f"Refund Processed \u2013 \u20b9{float(refund.amount):,.0f} | Insight Institute"
    text_body  = (
        f"Dear {student_name},\n\n"
        f"A refund of \u20b9{amount_fmt} has been successfully processed to your original payment source.\n\n"
        f"Receipt No : {payment.receipt_number}\n"
        f"Refund ID  : {rp_refund_id or 'N/A (offline)'}\n"
        f"Amount     : \u20b9{amount_fmt}\n"
        f"Date       : {refund_date}\n"
        f"Reason     : {refund.reason or 'N/A'}\n\n"
        f"Online refunds typically reflect within 5\u20137 business days depending on your bank.\n\n"
        f"Thank you,\nInsight Institute of Professional Studies"
    )
    template_context = {
        'student_name':        student_name,
        'amount':              amount_fmt,
        'razorpay_refund_id':  rp_refund_id or 'N/A (offline refund)',
        'razorpay_payment_id': payment.transaction_ref or 'N/A',
        'refund_date':         refund_date,
        'reason':              refund.reason,
        'primary_color':       '#ed7c31',
        'org_name':            getattr(org, 'name', 'Insight Institute of Professional Studies'),
    }

    # Email: student + parent
    emails = set()
    if student_user and getattr(student_user, 'email', None):
        emails.add(student_user.email)
    try:
        admission = student.admission
        if getattr(admission, 'email_parent', None):
            emails.add(admission.email_parent)
    except Exception:
        pass

    for email_addr in filter(None, emails):
        try:
            send_email(
                to=email_addr,
                subject=subject,
                text=text_body,
                template='emails/refund_confirmation.html',
                template_context=template_context,
                organization=org,
            )
            logger.info(f"[Refund] Email sent to {email_addr}")
        except Exception as e:
            logger.error(f"[Refund] Email to {email_addr} failed: {e}")

    # WhatsApp: student + parent phones
    try:
        from chat.notifications import send_whatsapp_with_fallback
        wa_message = (
            f"\u2705 *Refund Processed \u2014 Insight Institute*\n\n"
            f"Dear {student_name},\n\n"
            f"A refund of *\u20b9{float(refund.amount):,.0f}* has been processed.\n\n"
            f"\ud83c\udd94 Refund ID: {rp_refund_id or 'N/A'}\n"
            f"\ud83d\udcc5 Date: {refund_date}\n"
            f"\ud83d\udcdd Reason: {refund.reason or 'N/A'}\n\n"
            f"Online refunds reflect within *5\u20137 business days*.\n"
            f"\u2014 Insight Institute of Professional Studies"
        )
        phones = set()
        try:
            admission = student.admission
            if getattr(admission, 'phone_student', None):
                phones.add(admission.phone_student)
            if getattr(admission, 'phone_father', None):
                phones.add(admission.phone_father)
        except Exception:
            pass
        if student_user and getattr(student_user, 'phone', None):
            phones.add(student_user.phone)

        for phone in filter(None, phones):
            try:
                send_whatsapp_with_fallback(
                    to=phone,
                    template_name="refund_confirmation_",
                    language_code="en",
                    components=[{"type": "body", "parameters": [{"type": "text", "text": student_name},{"type": "text", "text": amount_fmt},{"type": "text", "text": rp_refund_id or 'N/A'},{"type": "text", "text": refund_date},{"type": "text", "text": refund.reason or 'N/A'}]}],
                    fallback_body=wa_message,
                )
                logger.info(f"[Refund] WhatsApp sent to {phone}")
            except Exception as e:
                logger.error(f"[Refund] WhatsApp to {phone} failed: {e}")
    except Exception as wa_err:
        logger.error(f"[Refund] WhatsApp error: {wa_err}")

        
class RefundCreateView(APIView):

    def post(self, request):
        serializer = RefundCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {'success': False, 'message': 'Please fix the errors below.', 'errors': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        refund = serializer.save(
            processed_by=request.user if request.user.is_authenticated else None,
        )

        rp_refund_id = None
        rp_error = None
        
        # If refund is created as completed immediately, trigger Razorpay and notifications
        if refund.status == 'completed':
            update_student_fee_status(refund.payment.student_fee_id)
            rp_refund_id, rp_error = trigger_razorpay_refund(refund)
            
            try:
                send_refund_notifications(refund=refund, rp_refund_id=rp_refund_id)
            except Exception as notif_err:
                logger.error(f"[Refund] Notification failed for Refund {refund.id}: {notif_err}")

        response_data = RefundListSerializer(refund).data
        if rp_refund_id:
            response_data['razorpay_refund_id'] = rp_refund_id
        if rp_error:
            response_data['razorpay_warning'] = f'Local refund recorded, but Razorpay refund failed: {rp_error}'

        return Response(
            {'success': True, 'message': 'Refund created.', 'data': response_data},
            status=status.HTTP_201_CREATED,
        )


class RefundUpdateView(APIView):
    """PATCH to mark refund as completed/rejected."""

    def patch(self, request, pk):
        try:
            queryset = Refund.objects.all()
            if getattr(request.user, 'organization', None):
                queryset = queryset.filter(payment__student__branch__organization=request.user.organization)
            refund = queryset.get(pk=pk)
        except Refund.DoesNotExist:
            return Response({'success': False, 'message': 'Refund not found.'}, status=status.HTTP_404_NOT_FOUND)

        new_status = request.data.get('status')
        if new_status not in ('completed', 'rejected'):
            return Response(
                {'success': False, 'message': 'Status must be completed or rejected.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        old_status = refund.status
        refund.status = new_status
        refund.save()

        rp_refund_id = None
        rp_error = None
        
        if new_status == 'completed' and old_status != 'completed':
            update_student_fee_status(refund.payment.student_fee_id)
            rp_refund_id, rp_error = trigger_razorpay_refund(refund)
            
            try:
                send_refund_notifications(refund=refund, rp_refund_id=rp_refund_id)
            except Exception as notif_err:
                logger.error(f"[Refund] Notification failed for Refund {refund.id}: {notif_err}")

        response_data = RefundListSerializer(refund).data
        if rp_refund_id:
            response_data['razorpay_refund_id'] = rp_refund_id
        if rp_error:
            response_data['razorpay_warning'] = f'Local refund recorded, but Razorpay refund failed: {rp_error}'

        return Response(
            {'success': True, 'message': f'Refund {new_status}.', 'data': response_data},
        )


# ═══════════════════════════════════════════════════════════════════════════════
#  Bank Account Views
# ═══════════════════════════════════════════════════════════════════════════════

class BankAccountListView(APIView):
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['is_active']
    search_fields = ['name', 'bank_name', 'account_number', 'ifsc_code']
    ordering_fields = '__all__'

    def get(self, request):
        queryset = BankAccount.objects.all()
        is_active = request.GET.get('is_active')
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')
            
        queryset = apply_filters(self, request, queryset)
        
        serializer = BankAccountListSerializer(queryset, many=True)
        return Response({'success': True, 'count': queryset.count(), 'data': serializer.data})

    def post(self, request):
        serializer = BankAccountCreateUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({'success': False, 'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
        bank = serializer.save()
        return Response(
            {'success': True, 'message': 'Bank account created.',
             'data': BankAccountListSerializer(bank).data},
            status=status.HTTP_201_CREATED,
        )


class BankAccountDetailView(APIView):

    def _get(self, pk):
        try:
            return BankAccount.objects.get(pk=pk)
        except BankAccount.DoesNotExist:
            return None

    def get(self, request, pk):
        obj = self._get(pk)
        if obj is None:
            return Response({'success': False, 'message': 'Bank account not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response({'success': True, 'data': BankAccountListSerializer(obj).data})

    def patch(self, request, pk):
        obj = self._get(pk)
        if obj is None:
            return Response({'success': False, 'message': 'Bank account not found.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = BankAccountCreateUpdateSerializer(obj, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response({'success': False, 'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
        serializer.save()
        return Response({'success': True, 'message': 'Bank account updated.',
                         'data': BankAccountListSerializer(obj).data})

    def delete(self, request, pk):
        obj = self._get(pk)
        if obj is None:
            return Response({'success': False, 'message': 'Bank account not found.'}, status=status.HTTP_404_NOT_FOUND)
        obj.delete()
        return Response({'success': True, 'message': 'Bank account deleted.'})


# ═══════════════════════════════════════════════════════════════════════════════
#  Fee Report View
# ═══════════════════════════════════════════════════════════════════════════════

class FeeReportView(APIView):
    """GET /api/v1/fees/report/ — fee collection report."""

    def get(self, request):
        course_id = request.GET.get('course_id')
        month = request.GET.get('month')   # YYYY-MM
        year = request.GET.get('year')

        # Base queryset — student fees
        sf_qs = StudentFee.objects.all()
        if getattr(request.user, 'organization', None):
            sf_qs = sf_qs.filter(student__branch__organization=request.user.organization)

        if course_id:
            sf_qs = sf_qs.filter(fee_structure__course_id=course_id)

        total_billed = sf_qs.aggregate(total=Sum('total_amount'))['total'] or 0
        total_discount = sf_qs.aggregate(total=Sum('discount'))['total'] or 0
        total_paid = sf_qs.aggregate(total=Sum('amount_paid'))['total'] or 0
        total_pending = max(0, total_billed - total_discount - total_paid)
        
        net_billed = total_billed - total_discount
        collected_pct = round((total_paid / net_billed) * 100, 2) if net_billed > 0 else 0
        pending_pct = round((total_pending / net_billed) * 100, 2) if net_billed > 0 else 0
        
        total_overdue = sf_qs.filter(status='overdue').aggregate(
            total=Sum('total_amount') - Sum('discount') - Sum('amount_paid')
        )['total'] or 0
        total_overdue = max(0, total_overdue)

        total_partial = sf_qs.filter(status='partial').aggregate(
            total=Sum('total_amount') - Sum('discount') - Sum('amount_paid')
        )['total'] or 0
        total_partial = max(0, total_partial)

        total_approval_pending = sf_qs.filter(status='approval_pending').aggregate(
            total=Sum('total_amount') - Sum('discount') - Sum('amount_paid')
        )['total'] or 0
        total_approval_pending = max(0, total_approval_pending)

        # Collection by payment mode
        payment_qs = Payment.objects.filter(status='verified')
        if getattr(request.user, 'organization', None):
            payment_qs = payment_qs.filter(student__branch__organization=request.user.organization)
        if month:
            parts = month.split('-')
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                payment_qs = payment_qs.filter(payment_date__year=int(parts[0]), payment_date__month=int(parts[1]))
            elif month.isdigit():
                payment_qs = payment_qs.filter(payment_date__month=int(month))
        if year:
            payment_qs = payment_qs.filter(payment_date__year=int(year))

        from .models import Refund
        refund_qs = Refund.objects.filter(status='completed', payment__in=payment_qs)
        refunds_by_mode = {}
        for row in refund_qs.values('payment__payment_mode').annotate(total=Sum('amount')):
            refunds_by_mode[row['payment__payment_mode']] = row['total']

        collection_by_mode = {}
        for row in payment_qs.values('payment_mode').annotate(total=Sum('amount')):
            mode = row['payment_mode']
            net = row['total'] - refunds_by_mode.get(mode, 0)
            if net > 0:
                collection_by_mode[mode] = net

        # Monthly trend (last 6 months)
        from django.db.models.functions import TruncMonth
        monthly_trend = []
        trend_qs = payment_qs.annotate(
            month_group=TruncMonth('payment_date')
        ).values('month_group').annotate(
            collected=Sum('amount')
        ).order_by('month_group')
        monthly_trend_dict = {}
        for row in trend_qs:
            month_str = row['month_group'].strftime('%Y-%m') if row['month_group'] else None
            if month_str:
                monthly_trend_dict[month_str] = row['collected']

        trend_refunds = refund_qs.annotate(
            month_group=TruncMonth('payment__payment_date')
        ).values('month_group').annotate(
            refunded=Sum('amount')
        )
        for row in trend_refunds:
            month_str = row['month_group'].strftime('%Y-%m') if row['month_group'] else None
            if month_str and month_str in monthly_trend_dict:
                monthly_trend_dict[month_str] -= row['refunded']
                if monthly_trend_dict[month_str] < 0:
                    monthly_trend_dict[month_str] = 0
                    
        for month_str, collected in sorted(monthly_trend_dict.items()):
            monthly_trend.append({
                'month': month_str,
                'collected': collected,
            })

        data = {
            'total_billed': total_billed,
            'total_collected': total_paid,
            'collected_percentage': collected_pct,
            'total_pending': total_pending,
            'pending_percentage': pending_pct,
            "total_discount":total_discount,
            'total_overdue': total_overdue,
            'total_partial': total_partial,
            'total_approval_pending': total_approval_pending,
            'collection_by_mode': collection_by_mode,
            'monthly_trend': monthly_trend,
        }
        return Response({'success': True, 'data': data})

class StudentFeeSummaryView(APIView):
    """GET /api/v1/fees/student-fees/summary/ — summary of student fees grouped by status."""

    def get(self, request):
        qs = StudentFee.objects.all()
        if getattr(request.user, 'organization', None):
            qs = qs.filter(student__branch__organization=request.user.organization)

        course_id = request.GET.get('course_id')
        batch_id = request.GET.get('batch_id')
        if course_id:
            qs = qs.filter(fee_structure__course_id=course_id)
        if batch_id:
            qs = qs.filter(fee_structure__batch_id=batch_id)

        # Aggregate by status
        summary_data = qs.values('status').annotate(
            student_count=Count('id'),
            total_amount=Sum('total_amount'),
            total_paid=Sum('amount_paid'),
            total_discount=Sum('discount')
        )

        status_choices_dict = dict(FEE_STATUS_CHOICES)
        results = []
        for item in summary_data:
            t_amount = item['total_amount'] or 0
            t_paid = item['total_paid'] or 0
            t_discount = item['total_discount'] or 0
            amount_due = max(0, t_amount - t_discount - t_paid)
            
            net_amount = max(0, t_amount - t_discount)
            paid_pct = round((t_paid / net_amount) * 100, 2) if net_amount > 0 else 0
            due_pct = round((amount_due / net_amount) * 100, 2) if net_amount > 0 else 0

            results.append({
                'status': item['status'],
                'status_display': status_choices_dict.get(item['status'], item['status']),
                'student_count': item['student_count'],
                'total_amount': t_amount,
                'total_paid': t_paid,
                'paid_percentage': paid_pct,
                'total_discount': t_discount,
                'amount_due': amount_due,
                'due_percentage': due_pct
            })

        return Response({'success': True, 'data': results})

def _user_role(user):
    from core.utils import get_user_role
    return get_user_role(user)

class MyFeesAPIView(APIView):
    """
    Returns the fee and payment records for the authenticated student based on their token.
    Allows submitting remaining fee payment:
      - payment_type: 'full_payment' | 'finance'
      - payment_choice: 'online' (generates Razorpay link) | 'cash' | 'cheque' (uploads proof)
    """
    # permission_classes = [IsAuthenticated]
    
    def get(self, request):
        user = request.user
        role = _user_role(user)
        
        if role not in ['student', 'parents']:
            return Response({'success': False, 'message': 'Only students or parents can access this API.'}, status=403)
            
        from students.models import Student, ParentLink
        try:
            if role == 'student':
                student = Student.objects.select_related('admission', 'branch').get(user=user)
            else:
                student_id = request.GET.get('student_id')
                if student_id:
                    link = ParentLink.objects.select_related('student__admission', 'student__branch').get(parent=user, student_id=student_id)
                    student = link.student
                else:
                    link = ParentLink.objects.select_related('student__admission', 'student__branch').filter(parent=user).first()
                    if not link:
                        return Response({'success': False, 'message': 'No linked students found.'}, status=404)
                    student = link.student
        except (Student.DoesNotExist, ParentLink.DoesNotExist):
            return Response({'success': False, 'message': 'Student profile not found or access denied.'}, status=404)
            
        student_fees = StudentFee.objects.select_related('fee_structure').filter(student=student).order_by('-created_at')
        payments = Payment.objects.filter(student=student).order_by('-payment_date', '-created_at')
        
        from .models import Refund
        from .serializers import RefundListSerializer
        
        refunds = Refund.objects.filter(payment__student=student).order_by('-created_at')
        
        fee_serializer = StudentFeeListSerializer(student_fees, many=True, context={'request': request})
        payment_serializer = PaymentListSerializer(payments, many=True, context={'request': request})
        refund_serializer = RefundListSerializer(refunds, many=True, context={'request': request})
        
        # Summary
        total_billed = student_fees.aggregate(total=Sum('total_amount'))['total'] or 0
        total_discount = student_fees.aggregate(total=Sum('discount'))['total'] or 0
        total_paid = student_fees.aggregate(total=Sum('amount_paid'))['total'] or 0
        total_due = max(0, total_billed - total_discount - total_paid)

        admission_id = getattr(student, 'admission_id', None)
        admission_number = getattr(student, 'admission_number', None)

        # ── 15-Day Finance Rule Notice ─────────────────────────────────────────
        finance_notice = None
        remaining_fee_options = None

        if total_due > 0:
            # Enrolled date when credentials were generated & issued
            enrolled_datetime = getattr(student, 'enrolled_at', None) or getattr(student, 'created_at', None) or timezone.now()
            enrolled_date = enrolled_datetime.date() if hasattr(enrolled_datetime, 'date') else enrolled_datetime

            finance_deadline_date = enrolled_date + timezone.timedelta(days=15)
            today = timezone.now().date()
            days_left = (finance_deadline_date - today).days

            if days_left > 0:
                is_moved_to_finance = False
                note_message = (
                    f"Please pay your remaining fee of ₹{total_due:,.0f} within 15 days of receiving your login credentials "
                    f"(deadline: {finance_deadline_date.strftime('%d %b %Y')}, {days_left} day(s) remaining). "
                    "If not paid within 15 days, your fee balance will automatically be moved to the finance process."
                )
            elif days_left == 0:
                is_moved_to_finance = False
                note_message = (
                    f"Today is the final day (deadline: {finance_deadline_date.strftime('%d %b %Y')}) to pay your remaining fee of ₹{total_due:,.0f}. "
                    "If not paid today, your fee balance will automatically be moved to the finance process tomorrow."
                )
            else:
                is_moved_to_finance = True
                days_overdue = abs(days_left)
                note_message = (
                    f"The 15-day payment window for remaining fees expired on {finance_deadline_date.strftime('%d %b %Y')} "
                    f"({days_overdue} day(s) ago). Your remaining fee balance of ₹{total_due:,.0f} has been moved to the finance process. "
                    "Our finance team will coordinate the finance/loan process with you."
                )
                # Auto-sync admission payment_type to finance if not already set
                if getattr(student, 'admission', None) and student.admission.payment_type != 'finance':
                    student.admission.payment_type = 'finance'
                    student.admission.save(update_fields=['payment_type', 'updated_at'])

            finance_notice = {
                'enrolled_date': enrolled_date.isoformat(),
                'deadline_date': finance_deadline_date.isoformat(),
                'deadline_date_display': finance_deadline_date.strftime('%d %b %Y'),
                'days_left': max(0, days_left),
                'days_overdue': abs(days_left) if days_left < 0 else 0,
                'is_moved_to_finance': is_moved_to_finance,
                'status': 'moved_to_finance' if is_moved_to_finance else 'pending_payment',
                'note': note_message,
            }

            remaining_fee_options = {
                'amount_due': float(total_due),
                'finance_notice': finance_notice,
                'payment_types': [
                    {'key': 'full_payment', 'label': 'Full Payment'},
                    {'key': 'finance', 'label': 'Finance (No Immediate Payment)'},
                ],
                'payment_choices': [
                    {'key': 'online', 'label': 'Online Transfer (Razorpay)'},
                    {'key': 'cash', 'label': 'Cash'},
                    {'key': 'cheque', 'label': 'Cheque'},
                ],
                'instruction': (
                    f"{note_message} "
                    'To pay remaining fees, submit POST /api/v1/fees/my-fees/ with payment_type and payment_choice. '
                    'If full_payment and online: Razorpay link is generated. '
                    'If full_payment and cash/cheque: upload payment_proof and transaction_ref. '
                    'If finance: finance option is registered.'
                ),
            }

        return Response({
            'success': True, 
            'role': role, 
            'student_id': str(student.id),
            'admission_id': admission_id,
            'admission_number': admission_number,
            'data': {
                'admission_id': admission_id,
                'admission_number': admission_number,
                'is_fully_paid': (total_due == 0),
                'summary': {
                    'total_billed': total_billed,
                    'total_discount': total_discount,
                    'total_paid': total_paid,
                    'total_due': total_due,
                },
                'finance_notice': finance_notice,
                'remaining_fee_options': remaining_fee_options,
                'fees': fee_serializer.data,
                'installments': [],  # Installments disabled for this flow (models/tables retained)
                'installments_enabled': False,
                'payments': payment_serializer.data,
                'refunds': refund_serializer.data
            }
        })

    def post(self, request):
        user = request.user
        role = _user_role(user)
        
        if role not in ['student', 'parents']:
            return Response({'success': False, 'message': 'Only students or parents can access this API.'}, status=403)
            
        import re
        import time
        from students.models import Student, ParentLink

        try:
            if role == 'student':
                student = Student.objects.select_related('admission', 'branch').get(user=user)
            else:
                student_id = request.data.get('student_id') or request.GET.get('student_id')
                if student_id:
                    link = ParentLink.objects.select_related('student__admission', 'student__branch').get(parent=user, student_id=student_id)
                    student = link.student
                else:
                    link = ParentLink.objects.select_related('student__admission', 'student__branch').filter(parent=user).first()
                    if not link:
                        return Response({'success': False, 'message': 'No linked students found.'}, status=404)
                    student = link.student
        except (Student.DoesNotExist, ParentLink.DoesNotExist):
            return Response({'success': False, 'message': 'Student profile not found or access denied.'}, status=404)

        student_fee = StudentFee.objects.select_related('fee_structure').filter(student=student).order_by('-created_at').first()
        if not student_fee:
            return Response({'success': False, 'message': 'No student fee record found.'}, status=404)

        amount_due = student_fee.amount_due
        if amount_due <= 0:
            return Response({
                'success': False,
                'message': 'No remaining fees due. Your fee has already been fully paid.',
                'data': {
                    'total_amount': float(student_fee.total_amount),
                    'amount_paid': float(student_fee.amount_paid),
                    'amount_due': 0,
                    'status': student_fee.status,
                }
            }, status=status.HTTP_400_BAD_REQUEST)

        payment_type = (request.data.get('payment_type') or 'full_payment').strip().lower()
        payment_choice = (request.data.get('payment_choice') or request.data.get('payment_mode') or 'online').strip().lower()

        # Validate payment_type
        if payment_type not in ('full_payment', 'finance'):
            return Response({
                'success': False,
                'message': "Invalid payment_type. Must be 'full_payment' or 'finance'."
            }, status=status.HTTP_400_BAD_REQUEST)

        # ── 1. Finance Option ──────────────────────────────────────────────────
        if payment_type == 'finance':
            if getattr(student, 'admission', None):
                student.admission.payment_type = 'finance'
                student.admission.save(update_fields=['payment_type', 'updated_at'])

            return Response({
                'success': True,
                'payment_type': 'finance',
                'message': 'Finance option selected. No immediate payment is required. Our finance team will assist you with the process.',
                'data': {
                    'student_id': str(student.id),
                    'admission_id': getattr(student, 'admission_id', None),
                    'student_fee_id': str(student_fee.id),
                    'payment_type': 'finance',
                    'amount_due': float(amount_due),
                    'status': 'finance_selected',
                }
            }, status=status.HTTP_200_OK)

        # ── 2. Full Payment ───────────────────────────────────────────────────
        if payment_choice not in ('online', 'cash', 'cheque'):
            return Response({
                'success': False,
                'message': "Invalid payment_choice. Must be 'online', 'cash', or 'cheque'."
            }, status=status.HTTP_400_BAD_REQUEST)

        # ── 2A. Online Payment via Razorpay ──────────────────────────────────
        if payment_choice == 'online':
            from .razorpay_service import create_payment_link

            unique_ref = f"SF_{int(time.time())}_{student_fee.id.hex[:16]}"
            course_name = (
                student_fee.fee_structure.name
                if (student_fee.fee_structure and student_fee.fee_structure.name)
                else 'Insight Institute'
            )
            description = f"Remaining Fee Payment ({course_name})"

            customer_phone = student.phone_student or ''
            clean_phone = re.sub(r'\D', '', customer_phone)
            if len(clean_phone) > 10:
                clean_phone = clean_phone[-10:]

            notes = {
                'student_fee_id': str(student_fee.id),
                'student_id': str(student.id),
                'payment_type': 'full_payment',
            }

            result = create_payment_link(
                amount=float(amount_due),
                reference_id=unique_ref,
                customer_name=student.full_name,
                customer_email=student.email or '',
                customer_contact=clean_phone,
                description=description,
                notes=notes,
            )

            if not result.get('success'):
                return Response({
                    'success': False,
                    'message': f"Failed to generate Razorpay payment link: {result.get('error', 'Unknown error')}",
                    'detail': result.get('detail'),
                }, status=status.HTTP_502_BAD_GATEWAY)

            rp_data = result.get('data', {})
            link_url = rp_data.get('short_url') or rp_data.get('url') or ''
            link_id = rp_data.get('id')

            if getattr(student, 'admission', None):
                student.admission.razorpay_payment_link = link_url
                student.admission.razorpay_payment_link_id = link_id
                student.admission.save(update_fields=['razorpay_payment_link', 'razorpay_payment_link_id', 'updated_at'])

            return Response({
                'success': True,
                'payment_type': 'full_payment',
                'payment_choice': 'online',
                'message': 'Razorpay payment link generated successfully for remaining fees.',
                'data': {
                    'student_id': str(student.id),
                    'admission_id': getattr(student, 'admission_id', None),
                    'student_fee_id': str(student_fee.id),
                    'amount': float(amount_due),
                    'payment_link_url': link_url,
                    'payment_link_id': link_id,
                    'payment_mode': 'online',
                    'status': 'link_generated',
                }
            }, status=status.HTTP_200_OK)

        # ── 2B. Cash / Cheque with Proof Upload ──────────────────────────────
        payment_proof = request.FILES.get('payment_proof') or request.FILES.get('payment_screenshot')
        transaction_ref = (request.data.get('transaction_ref') or request.data.get('transaction_id') or '').strip()
        payment_note = (request.data.get('payment_note') or request.data.get('note') or '').strip()

        if payment_choice == 'cheque' and not transaction_ref and not payment_proof:
            return Response({
                'success': False,
                'message': 'Please provide the cheque number (transaction_ref) or upload a photo of the cheque (payment_proof).'
            }, status=status.HTTP_400_BAD_REQUEST)

        amount_to_pay = float(request.data.get('amount') or amount_due)
        if amount_to_pay <= 0:
            amount_to_pay = float(amount_due)

        note_text = f"Remaining fee payment ({payment_choice.upper()}) submitted by student."
        if payment_note:
            note_text += f" Note: {payment_note}"

        payment = Payment.objects.create(
            student=student,
            admission=getattr(student, 'admission', None),
            student_fee=student_fee,
            amount=amount_to_pay,
            payment_mode=payment_choice,
            transaction_ref=transaction_ref,
            payment_proof=payment_proof,
            status='approval_pending',
            payment_date=timezone.now().date(),
            note=note_text,
        )

        if getattr(student, 'admission', None):
            student.admission.add_payment_history_entry('offline_payment_selected', {
                'payment_choice': payment_choice,
                'payment_type': 'full_payment',
                'amount_to_pay': float(amount_to_pay),
                'transaction_id': transaction_ref,
                'status': 'approval_pending',
                'date': timezone.now().date().isoformat(),
                'note': note_text,
            })

        try:
            from core.utils import notify_users_by_role
            notify_users_by_role(
                roles=['accountant', 'super_admin'],
                title=f'Remaining Fee Payment Proof Submitted ({payment_choice.title()})',
                body=(
                    f"Student {student.full_name} submitted remaining fee payment proof of ₹{amount_to_pay:,.0f} "
                    f"via {payment_choice.title()}. Transaction/Ref: {transaction_ref or 'N/A'}. Pending verification."
                ),
                organization=student.branch.organization if getattr(student, 'branch', None) else None,
                branch=student.branch if getattr(student, 'branch', None) else None,
            )
        except Exception as notify_err:
            logger.error(f"Failed to notify admins of remaining fee payment: {notify_err}")

        proof_url = request.build_absolute_uri(payment.payment_proof.url) if payment.payment_proof else None

        return Response({
            'success': True,
            'payment_type': 'full_payment',
            'payment_choice': payment_choice,
            'message': (
                f"Remaining fee payment proof for {payment_choice.title()} submitted successfully! "
                "It is pending verification by the accountant and super admin."
            ),
            'data': {
                'payment_id': str(payment.id),
                'student_id': str(student.id),
                'admission_id': getattr(student, 'admission_id', None),
                'student_fee_id': str(student_fee.id),
                'amount': float(payment.amount),
                'payment_mode': payment.payment_mode,
                'transaction_ref': payment.transaction_ref,
                'status': payment.status,
                'status_display': payment.get_status_display(),
                'payment_date': payment.payment_date.isoformat(),
                'payment_proof_url': proof_url,
            }
        }, status=status.HTTP_201_CREATED)

import json
from django.conf import settings
from rest_framework.permissions import AllowAny
from .razorpay_service import (
    create_payment_link,
    build_upi_link,
    fetch_payment_link,
    cancel_payment_link,
    fetch_payment,
    create_refund,
    process_payment_link_paid_event,
    process_payment_link_cancelled_event,
    process_refund_processed_event,
    is_razorpay_enabled,
    verify_webhook_signature,
)


class RazorpayGeneratePaymentLinkView(APIView):
    """
    POST /api/v1/fees/razorpay/generate-link/
    Body: {
        "student_fee_id": "<uuid>",
        "payment_type":   "token_full" | "token_finance",
        "amount":         5000           # optional override
    }
    payment_type='token_full'    → charges the full outstanding amount
    payment_type='token_finance' → charges only the token/registration amount
    """

    def post(self, request):
        student_fee_id  = request.data.get('student_fee_id')
        payment_type    = request.data.get('payment_type', 'token_full')
        override_amount = request.data.get('amount')

        if not student_fee_id:
            return Response({'success': False, 'message': 'student_fee_id is required.'}, status=400)

        try:
            sf = StudentFee.objects.select_related('student', 'fee_structure').get(pk=student_fee_id)
        except StudentFee.DoesNotExist:
            return Response({'success': False, 'message': 'Student fee not found.'}, status=404)

        student, fee_structure = sf.student, sf.fee_structure

        # Resolve amount
        if override_amount:
            amount = float(override_amount)
        elif payment_type == 'token_full':
            amount = float(sf.amount_due)
        else:
            amount = float(fee_structure.token_amount) if (fee_structure and fee_structure.token_amount) else float(sf.amount_due)

        if amount <= 0:
            return Response({'success': False, 'message': 'Amount must be greater than zero.'}, status=400)

        admission = None
        try:
            from onboarding.models import Admission
            admission = Admission.objects.filter(email=student.email).order_by('-submitted_at').first()
        except Exception:
            pass

        import time
        ref_id = f"SF_{int(time.time())}_{sf.id.hex[:16]}"
        notes = {
            'student_fee_id': str(sf.id),
            'student_id': str(student.id),
            'payment_type': str(payment_type),
        }

        result = create_payment_link(
            amount               = amount,
            reference_id         = ref_id,
            customer_name        = student.full_name,
            customer_email       = student.email or '',
            customer_contact     = student.phone or '',
            description          = f"Fee Payment — {fee_structure.name if fee_structure else 'Insight Institute'}",
            notes                = notes,
        )

        if not result['success']:
            return Response({'success': False, 'message': result['error'], 'detail': result.get('detail')}, status=502)

        rp = result['data']

        # Persist link back to admission record if available
        try:
            if admission:
                admission.razorpay_payment_link    = rp.get('short_url', '')
                admission.razorpay_payment_link_id = rp.get('id', '')
                admission.save(update_fields=['razorpay_payment_link', 'razorpay_payment_link_id', 'updated_at'])
        except Exception:
            pass

        return Response({
            'success': True,
            'message': 'Razorpay payment link created.',
            'data': {
                'payment_link_id': rp.get('id'),
                'short_url':       rp.get('short_url'),
                'amount':          amount,
                'payment_type':    payment_type,
                'status':          rp.get('status'),
                'expire_by':       rp.get('expire_by'),
            }
        }, status=201)


class RazorpayDirectPaymentLinkView(APIView):
    """
    POST /api/v1/fees/razorpay/generate-direct-link/
    Generate a Razorpay payment link directly with the parameters passed in the body.
    Body parameters:
    - amount (required): Amount in INR
    - reference_id (required): Unique string identifier
    - customer_name (required): Payer name
    - customer_email (optional): Payer email
    - customer_contact (optional): Payer phone (10-digit)
    - description (optional): Description for payment
    - upi_id (optional): UPI ID
    """
    
    def post(self, request):
        amount = request.data.get('amount')
        reference_id = request.data.get('reference_id')
        customer_name = request.data.get('customer_name')
        
        if not amount or not reference_id or not customer_name:
            return Response({
                'success': False, 
                'message': 'amount, reference_id, and customer_name are required.'
            }, status=400)
            

        result = create_payment_link(
            amount=amount,
            reference_id=reference_id,
            customer_name=customer_name,
            customer_email=request.data.get('customer_email', ''),
            customer_contact=request.data.get('customer_contact', ''),
            description=request.data.get('description', 'Direct Payment'),
            upi_id=request.data.get('upi_id')
        )
        
        if not result['success']:
            return Response({'success': False, 'message': result['error'], 'detail': result.get('detail')}, status=502)
            
        return Response({
            'success': True,
            'message': 'Razorpay payment link created.',
            'data': result['data']
        }, status=201)



class RazorpayFetchPaymentLinkView(APIView):
    """
    GET /api/v1/fees/razorpay/payment-link/<link_id>/
    Fetch live status of a Razorpay payment link.
    """

    def get(self, request, link_id):
        result = fetch_payment_link(link_id)
        if not result['success']:
            return Response({'success': False, 'message': result['error'], 'detail': result.get('detail')}, status=404)
        return Response({'success': True, 'data': result['data']})


class RazorpayCancelPaymentLinkView(APIView):
    """
    POST /api/v1/fees/razorpay/cancel-link/<link_id>/
    Cancel/expire a Razorpay payment link.
    """

    def post(self, request, link_id):
        result = cancel_payment_link(link_id)
        if not result['success']:
            return Response({'success': False, 'message': result['error'], 'detail': result.get('detail')}, status=400)

        # Clear from any linked admission
        try:
            from onboarding.models import Admission
            Admission.objects.filter(razorpay_payment_link_id=link_id).update(
                razorpay_payment_link=None,
                razorpay_payment_link_id=None,
            )
        except Exception:
            pass

        return Response({'success': True, 'message': 'Payment link cancelled.', 'data': result['data']})


class RazorpayFetchPaymentView(APIView):
    """
    GET /api/v1/fees/razorpay/payment/<razorpay_payment_id>/
    Fetch full details of a Razorpay payment.
    """

    def get(self, request, razorpay_payment_id):
        result = fetch_payment(razorpay_payment_id)
        if not result['success']:
            return Response({'success': False, 'message': result['error'], 'detail': result.get('detail')}, status=404)
        return Response({'success': True, 'data': result['data']})


class RazorpayRefundView(APIView):
    """
    POST /api/v1/fees/razorpay/refund/
    Body: {
        "payment_id":       "pay_xxx",    # Razorpay payment ID
        "amount":           1000,         # INR amount to refund
        "reason":           "...",
        "local_payment_id": "<uuid>"      # optional â€” local Payment record to create Refund against
    }
    """

    def post(self, request):
        razorpay_payment_id = request.data.get('payment_id')
        amount              = request.data.get('amount')
        reason              = request.data.get('reason', '')
        local_payment_id    = request.data.get('local_payment_id')

        if not razorpay_payment_id or not amount:
            return Response({'success': False, 'message': 'payment_id and amount are required.'}, status=400)

        result = create_refund(payment_id=razorpay_payment_id, amount=amount, reason=reason)
        if not result['success']:
            return Response({'success': False, 'message': result['error'], 'detail': result.get('detail')}, status=502)

        rp = result['data']

        # Optionally create local Refund record
        local_refund = None
        if local_payment_id:
            try:
                local_payment = Payment.objects.get(pk=local_payment_id)
                local_refund  = Refund.objects.create(
                    payment      = local_payment,
                    amount       = float(amount),
                    reason       = reason,
                    status       = 'completed',
                    processed_by = request.user if request.user.is_authenticated else None,
                )
                update_student_fee_status(local_payment.student_fee_id)
            except Payment.DoesNotExist:
                logger.warning(f"Local payment {local_payment_id} not found â€” Razorpay refund still processed.")
            except Exception as exc:
                logger.error(f"Local refund record creation failed: {exc}")

        return Response({
            'success': True,
            'message': 'Refund initiated on Razorpay.',
            'data': {
                'razorpay_refund_id':  rp.get('id'),
                'razorpay_payment_id': razorpay_payment_id,
                'amount':              float(amount),
                'status':              rp.get('status'),
                'local_refund_id':     str(local_refund.id) if local_refund else None,
            }
        }, status=201)


class RazorpayWebhookView(APIView):
    """
    POST /api/v1/fees/razorpay/webhook/
    Receives and processes Razorpay webhook events.
    Register this URL in Razorpay Dashboard â†’ Webhooks.
    Supported events: payment_link.paid, refund.processed
    """

    def get_permissions(self):
        return [AllowAny()]

    def post(self, request):
        # Verify signature
        signature = request.headers.get('X-Razorpay-Signature', '')
        if not verify_webhook_signature(request.body, signature):
            logger.warning("Razorpay webhook: invalid signature â€” rejected.")
            return Response({'success': False, 'message': 'Invalid signature.'}, status=400)

        try:
            payload = json.loads(request.body)
        except json.JSONDecodeError:
            return Response({'success': False, 'message': 'Invalid JSON.'}, status=400)

        event = payload.get('event', '')
        logger.info(f"Razorpay webhook received: {event}")

        if event in ('payment_link.paid', 'payment_link.partially_paid'):
            process_payment_link_paid_event(payload)

        elif event == 'refund.processed':
            process_refund_processed_event(payload)
            
        elif event in ('payment_link.cancelled', 'payment_link.expired'):
            process_payment_link_cancelled_event(payload)

        # Always return 200 so Razorpay doesn't retry indefinitely
        return Response({'success': True})


class RazorpayWebhookTestView(APIView):
    """
    POST /api/v1/fees/razorpay/webhook/test/
    Safe test endpoint that simulates a 'payment_link.paid' webhook event
    without requiring a live Razorpay callback. Runs the full pipeline:
    - Payment record creation (SF_ flow) or Admission status update (ADM_ flow)
    - Receipt PDF auto-generation
    - Email dispatch (with PDF attachment)
    - WhatsApp notification (PDF document or text fallback)

    Request body:
    {
        "reference_id": "SF_<uuid>_token_full" | "ADM_<admission_id>",
        "amount": 5000,
        "rp_payment_id": "pay_TEST123"   (optional)
    }
    """

    def post(self, request):
        reference_id  = request.data.get('reference_id', '')
        amount_inr    = request.data.get('amount', 100)
        rp_payment_id = request.data.get('rp_payment_id') or f'pay_TEST_{reference_id[:8]}'

        if not reference_id:
            return Response(
                {
                    'success': False,
                    'message': (
                        'reference_id is required. '
                        'Examples: "SF_<uuid>_token_full" or "ADM_<admission_id>"'
                    ),
                },
                status=400,
            )

        amount_paise = int(float(amount_inr) * 100)
        simulated_payload = {
            'event': 'payment_link.paid',
            'payload': {
                'payment_link': {
                    'entity': {
                        'id': f'plink_TEST_{reference_id[:8]}',
                        'reference_id': reference_id,
                        'amount_paid': amount_paise,
                        'status': 'paid',
                    }
                },
                'payment': {
                    'entity': {
                        'id': rp_payment_id,
                        'amount': amount_paise,
                        'status': 'captured',
                    }
                },
            },
        }

        logger.info(
            '[RazorpayTest] Simulating payment_link.paid — '
            f'reference_id={reference_id}, amount=Rs.{amount_inr}'
        )

        result = process_payment_link_paid_event(simulated_payload)

        return Response({
            'success': True,
            'message': (
                'Webhook simulation complete. '
                'Check server logs and the recipient inbox / WhatsApp.'
            ),
            'simulated_payload': simulated_payload,
            'result': result,
        })

