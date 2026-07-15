import logging
from core.pagination import paginate_queryset

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.filters import SearchFilter, OrderingFilter
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
from .utils import update_student_fee_status, mark_installment_paid, get_installment_plan_status
from .services import send_payment_receipt

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
#  Fee Structure Views
# ═══════════════════════════════════════════════════════════════════════════════

class FeeStructureListView(APIView):
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['course', 'batch', 'is_active']
    search_fields = ['name']
    ordering_fields = '__all__'

    def get(self, request):
        queryset = FeeStructure.objects.select_related('course', 'batch').prefetch_related('student_fees').all()
        if getattr(request.user, 'organization', None):
            queryset = queryset.filter(
                Q(course__organization=request.user.organization) |
                Q(batch__organization=request.user.organization)
            )

        course_id = request.GET.get('course_id')
        batch_id = request.GET.get('batch_id')
        is_active = request.GET.get('is_active')

        if course_id:
            queryset = queryset.filter(course_id=course_id)
        if batch_id:
            queryset = queryset.filter(batch_id=batch_id)
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

    def _get(self, request, pk):
        try:
            queryset = FeeStructure.objects.select_related('course', 'batch').all()
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

        if student_id:
            queryset = queryset.filter(student_id=student_id)
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        if fee_structure_id:
            queryset = queryset.filter(fee_structure_id=fee_structure_id)

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
    filterset_fields = ['student', 'status', 'payment_mode']
    search_fields = ['student__first_name', 'student__surname', 'transaction_ref', 'receipt_number']
    ordering_fields = '__all__'

    def get(self, request):
        # Optimized: select_related for foreign keys
        queryset = Payment.objects.select_related('student', 'student_fee').prefetch_related('refunds').all()
        if getattr(request.user, 'organization', None):
            queryset = queryset.filter(student__branch__organization=request.user.organization)

        student_id = request.GET.get('student_id')
        payment_status = request.GET.get('status')
        payment_mode = request.GET.get('payment_mode')
        date_from = request.GET.get('date_from')
        date_to = request.GET.get('date_to')

        if student_id:
            queryset = queryset.filter(student_id=student_id)
        if payment_status:
            queryset = queryset.filter(status=payment_status)
        if payment_mode:
            queryset = queryset.filter(payment_mode=payment_mode)
        if date_from:
            queryset = queryset.filter(payment_date__gte=date_from)
        if date_to:
            queryset = queryset.filter(payment_date__lte=date_to)

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

        return Response(
            {'success': True, 'message': 'Payment recorded.',
             'data': PaymentDetailSerializer(payment).data},
            status=status.HTTP_201_CREATED,
        )


class PaymentDetailView(APIView):

    def _get(self, request, pk):
        try:
            queryset = Payment.objects.select_related('student', 'student_fee').all()
            if getattr(request.user, 'organization', None):
                queryset = queryset.filter(student__branch__organization=request.user.organization)
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
        try:
            queryset = Payment.objects.select_related(
                'installment_item__plan', 'student_fee', 'student'
            ).all()
            if getattr(request.user, 'organization', None):
                queryset = queryset.filter(student__branch__organization=request.user.organization)
            payment = queryset.get(pk=pk)
        except Payment.DoesNotExist:
            return Response({'success': False, 'message': 'Payment not found.'}, status=status.HTTP_400_BAD_REQUEST)

        if payment.status != 'approval_pending':
            return Response(
                {'success': False, 'message': f'Payment is already {payment.status}.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Prevent approving/verifying payments linked to pending_approval installment plans.
        # This enforces the conditional approval workflow from InstallmentPlanCreateView
        # (status based on course_type and # of items; uses approved_by/approved_at).
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
        payment.status = new_status
        payment.verified_by = request.user if request.user.is_authenticated else None
        payment.verified_at = timezone.now()
        if new_status == 'rejected':
            payment.note = serializer.validated_data.get('note', '')
        payment.save()

        # Recalculate student fee status
        update_student_fee_status(payment.student_fee_id)

        # If linked to installment item, check if paid
        if payment.installment_item_id:
            try:
                mark_installment_paid(payment.installment_item_id)
            except Exception as e:
                logger.error(f'Failed to mark installment paid: {e}')

        # Send emails on verification/rejection
        from django.core.mail import EmailMessage
        from django.conf import settings
        
        to_emails = []
        if getattr(payment.student, 'email', None):
            to_emails.append(payment.student.email)
        if getattr(payment.student, 'email_parent', None):
            to_emails.append(payment.student.email_parent)
        if not to_emails and getattr(payment.student, 'user', None) and getattr(payment.student.user, 'email', None):
            to_emails.append(payment.student.user.email)

        if new_status == 'verified':
            send_payment_receipt(payment)
        elif new_status == 'rejected' and to_emails:
            subject = f"Payment Rejected - {payment.transaction_ref or payment.id}"
            body = f"Dear {payment.student.first_name},\n\nUnfortunately, your payment of ₹{payment.amount} has been rejected.\n\n"
            if getattr(payment, 'note', None):
                body += f"Reason: {payment.note}\n\n"
            body += "Please contact the administration for more details.\n\nInsight Institute"
            
            email = EmailMessage(
                subject,
                body,
                settings.DEFAULT_FROM_EMAIL,
                to_emails
            )
            try:
                email.send(fail_silently=False)
            except Exception as e:
                logger.error(f"Failed to send rejection email: {e}")

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

        # If refund is completed, update student fee
        if refund.status == 'completed':
            update_student_fee_status(refund.payment.student_fee_id)

        return Response(
            {'success': True, 'message': 'Refund created.',
             'data': RefundListSerializer(refund).data},
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

        refund.status = new_status
        refund.save()

        if new_status == 'completed':
            update_student_fee_status(refund.payment.student_fee_id)

        return Response(
            {'success': True, 'message': f'Refund {new_status}.',
             'data': RefundListSerializer(refund).data},
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
            'total_pending': total_pending,
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

            results.append({
                'status': item['status'],
                'status_display': status_choices_dict.get(item['status'], item['status']),
                'student_count': item['student_count'],
                'total_amount': t_amount,
                'total_paid': t_paid,
                'total_discount': t_discount,
                'amount_due': amount_due
            })

        return Response({'success': True, 'data': results})
