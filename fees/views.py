import logging
from core.pagination import paginate_queryset

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from django.db.models import Sum, Count, Q
from django.utils import timezone

from .models import (
    FeeStructure, StudentFee,
    InstallmentPlan, InstallmentItem,
    Payment, Refund, BankAccount,
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
from .utils import update_student_fee_status, mark_installment_paid

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
#  Fee Structure Views
# ═══════════════════════════════════════════════════════════════════════════════

class FeeStructureListView(APIView):

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
        search = request.GET.get('search')

        if course_id:
            queryset = queryset.filter(course_id=course_id)
        if batch_id:
            queryset = queryset.filter(batch_id=batch_id)
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')
        if search:
            queryset = queryset.filter(name__icontains=search)

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

    def get(self, request):
        # Optimized: prefetch_related for reverse relations
        queryset = StudentFee.objects.select_related('student', 'fee_structure').prefetch_related('payments', 'installment_plans').all()
        if getattr(request.user, 'organization', None):
            queryset = queryset.filter(student__organization=request.user.organization)

        student_id = request.GET.get('student_id')
        status_filter = request.GET.get('status')
        fee_structure_id = request.GET.get('fee_structure_id')

        if student_id:
            queryset = queryset.filter(student_id=student_id)
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        if fee_structure_id:
            queryset = queryset.filter(fee_structure_id=fee_structure_id)

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
                queryset = queryset.filter(student__organization=request.user.organization)
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
        from auth_user.models import User
        try:
            queryset = User.objects.filter(role='student')
            if getattr(request.user, 'organization', None):
                queryset = queryset.filter(organization=request.user.organization)
            student = queryset.get(id=student_id)
        except User.DoesNotExist:
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
                'student_name': student.name,
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

    def get(self, request):
        queryset = InstallmentPlan.objects.select_related(
            'student_fee__student', 'student_fee__fee_structure'
        ).prefetch_related('items').all()
        if getattr(request.user, 'organization', None):
            queryset = queryset.filter(student_fee__student__organization=request.user.organization)

        student_fee_id = request.GET.get('student_fee_id')
        plan_status = request.GET.get('status')

        if student_fee_id:
            queryset = queryset.filter(student_fee_id=student_fee_id)
        if plan_status:
            queryset = queryset.filter(status=plan_status)

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
        )
        for item in items_data:
            InstallmentItem.objects.create(
                plan=plan,
                amount=item['amount'],
                due_date=item['due_date'],
            )

        return Response(
            {'success': True, 'message': 'Installment plan created (pending approval).',
             'data': InstallmentPlanListSerializer(plan).data},
            status=status.HTTP_201_CREATED,
        )


class InstallmentPlanApproveView(APIView):

    def post(self, request, pk):
        try:
            queryset = InstallmentPlan.objects.all()
            if getattr(request.user, 'organization', None):
                queryset = queryset.filter(student_fee__student__organization=request.user.organization)
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

    def get(self, request):
        # Optimized: select_related for foreign keys
        queryset = Payment.objects.select_related('student', 'student_fee').prefetch_related('refunds').all()
        if getattr(request.user, 'organization', None):
            queryset = queryset.filter(student__organization=request.user.organization)

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
                queryset = queryset.filter(student__organization=request.user.organization)
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
            queryset = Payment.objects.all()
            if getattr(request.user, 'organization', None):
                queryset = queryset.filter(student__organization=request.user.organization)
            payment = queryset.get(pk=pk)
        except Payment.DoesNotExist:
            return Response({'success': False, 'message': 'Payment not found.'}, status=status.HTTP_404_NOT_FOUND)

        if payment.status != 'pending':
            return Response(
                {'success': False, 'message': f'Payment is already {payment.status}.'},
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

        return Response(
            {'success': True, 'message': f'Payment {new_status}.',
             'data': PaymentDetailSerializer(payment).data},
        )


# ═══════════════════════════════════════════════════════════════════════════════
#  Refund Views
# ═══════════════════════════════════════════════════════════════════════════════

class RefundListView(APIView):

    def get(self, request):
        queryset = Refund.objects.select_related('payment').all()
        if getattr(request.user, 'organization', None):
            queryset = queryset.filter(payment__student__organization=request.user.organization)
        refund_status = request.GET.get('status')
        if refund_status:
            queryset = queryset.filter(status=refund_status)

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
                queryset = queryset.filter(payment__student__organization=request.user.organization)
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

    def get(self, request):
        queryset = BankAccount.objects.all()
        is_active = request.GET.get('is_active')
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')
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
            sf_qs = sf_qs.filter(student__organization=request.user.organization)

        if course_id:
            sf_qs = sf_qs.filter(fee_structure__course_id=course_id)

        total_billed = sf_qs.aggregate(total=Sum('total_amount'))['total'] or 0
        total_discount = sf_qs.aggregate(total=Sum('discount'))['total'] or 0
        total_paid = sf_qs.aggregate(total=Sum('amount_paid'))['total'] or 0
        total_pending = total_billed - total_discount - total_paid
        total_overdue = sf_qs.filter(status='overdue').aggregate(
            total=Sum('total_amount') - Sum('discount') - Sum('amount_paid')
        )['total'] or 0

        # Collection by payment mode
        payment_qs = Payment.objects.filter(status='verified')
        if getattr(request.user, 'organization', None):
            payment_qs = payment_qs.filter(student__organization=request.user.organization)
        if month:
            payment_qs = payment_qs.filter(payment_date__month=int(month.split('-')[1]),
                                            payment_date__year=int(month.split('-')[0]))
        if year:
            payment_qs = payment_qs.filter(payment_date__year=int(year))

        collection_by_mode = {}
        for row in payment_qs.values('payment_mode').annotate(total=Sum('amount')):
            collection_by_mode[row['payment_mode']] = row['total']

        # Monthly trend (last 6 months)
        from django.db.models.functions import TruncMonth
        monthly_trend = []
        trend_qs = payment_qs.annotate(
            month_group=TruncMonth('payment_date')
        ).values('month_group').annotate(
            collected=Sum('amount')
        ).order_by('month_group')
        for row in trend_qs:
            monthly_trend.append({
                'month': row['month_group'].strftime('%Y-%m') if row['month_group'] else None,
                'collected': row['collected'],
            })

        data = {
            'total_billed': total_billed,
            'total_collected': total_paid,
            'total_pending': total_pending,
            'total_overdue': total_overdue,
            'collection_by_mode': collection_by_mode,
            'monthly_trend': monthly_trend,
        }
        return Response({'success': True, 'data': data})
