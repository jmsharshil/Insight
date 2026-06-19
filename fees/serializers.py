from rest_framework import serializers
from students.models import Student
from .models import (
    FeeStructure, StudentFee,
    InstallmentPlan, InstallmentItem,
    Payment, Refund, BankAccount,
    PAYMENT_MODE_CHOICES, PAYMENT_STATUS_CHOICES,
    FEE_STATUS_CHOICES, INSTALLMENT_PLAN_STATUS_CHOICES,
    REFUND_STATUS_CHOICES,
)
from .utils import get_installment_plan_status
from decimal import Decimal



# ═══════════════════════════════════════════════════════════════════════════════
#  Fee Structure
# ═══════════════════════════════════════════════════════════════════════════════

class FeeStructureListSerializer(serializers.ModelSerializer):
    course_name = serializers.CharField(source='course.name', read_only=True, default=None)
    batch_name = serializers.CharField(source='batch.name', read_only=True, default=None)
    level_name = serializers.CharField(source='level.name', read_only=True, default=None)

    class Meta:
        model = FeeStructure
        fields = ['id', 'name', 'course', 'course_name', 'batch', 'batch_name',
                  'level', 'level_name', 'total_amount', 'icsi_registration_fees',
                  'icsi_exam_fees', 'token_amount', 'is_active', 'created_at']


class FeeStructureDetailSerializer(serializers.ModelSerializer):
    course_name = serializers.CharField(source='course.name', read_only=True, default=None)
    batch_name = serializers.CharField(source='batch.name', read_only=True, default=None)
    level_name = serializers.CharField(source='level.name', read_only=True, default=None)

    class Meta:
        model = FeeStructure
        fields = '__all__'


class FeeStructureCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeeStructure
        fields = ['name', 'course', 'batch', 'level', 'total_amount', 'icsi_registration_fees',
                  'icsi_exam_fees', 'token_amount', 'description', 'is_active']

    def validate(self, data):
        """Ensure total_amount is consistent with fee breakdown components."""
        reg = data.get('icsi_registration_fees') or 0
        exam = data.get('icsi_exam_fees') or 0
        token = data.get('token_amount') or 0
        component_sum = reg + exam + token
        if component_sum > 0:
            if data.get('total_amount') and data['total_amount'] != component_sum:
                raise serializers.ValidationError({
                    'total_amount': f'Total must equal sum of components ({component_sum}) or be omitted.'
                })
            # If no total provided, it will be set by model.save()
            if 'total_amount' not in data:
                data['total_amount'] = component_sum
        return data

    def create(self, validated_data):
        # Remove total if it was set by validate (to let model compute in save)
        validated_data.pop('total_amount', None)
        fee_structure = super().create(validated_data)
        
        # Refresh to ensure computed total_amount from model.save() is loaded
        fee_structure.refresh_from_db()
        
        # Auto-assign the fee to students. Use level name mapping (CSEET, CSExecutive,
        # CS Professional) to match admission.course since course_type on levels is deprecated.
        from students.models import Student
        
        students_to_assign = set()
        
        if fee_structure.level:
            # Map level name to student's course field value
            level_name = fee_structure.level.name or ''
            level_upper = level_name.upper().replace(' ', '')
            if 'CSEET' in level_upper:
                course_val = 'cseet'
            elif 'EXECUTIVE' in level_upper:
                course_val = 'cs_executive'
            elif 'PROFESSIONAL' in level_upper:
                course_val = 'cs_professional'
            else:
                course_val = None
            if course_val:
                # Match students whose course matches the level (from admission)
                students = Student.objects.filter(
                    course=course_val, is_active=True
                )
                for s in students:
                    students_to_assign.add(s)
            else:
                # Fallback to level's related batches
                students = Student.objects.filter(
                    batch__course__levels=fee_structure.level,
                    is_active=True
                )
                for s in students:
                    students_to_assign.add(s)
        elif fee_structure.batch:
            students = Student.objects.filter(batch=fee_structure.batch, is_active=True)
            for s in students:
                students_to_assign.add(s)
        elif fee_structure.course:
            # Fallback to course if no specific batch or level
            students = Student.objects.filter(
                batch__course=fee_structure.course, is_active=True
            )
            for s in students:
                students_to_assign.add(s)

        # Create StudentFee for each student (skip students who already have one)
        existing_student_ids = set(
            StudentFee.objects.filter(
                student__in=students_to_assign
            ).values_list('student_id', flat=True)
        )
        student_fees_to_create = []
        for student in students_to_assign:
            if student.id in existing_student_ids:
                continue
            student_fees_to_create.append(
                StudentFee(
                    student=student,
                    fee_structure=fee_structure,
                    total_amount=fee_structure.total_amount,
                    discount=Decimal('0'),
                    amount_paid=Decimal('0'),
                    status='approval_pending'
                )
            )

        if student_fees_to_create:
            StudentFee.objects.bulk_create(student_fees_to_create)
            
            # Re-fetch the created StudentFees (bulk_create doesn't populate PKs on instances)
            # Auto-create basic InstallmentPlan + item for each. When student pays,
            # update_student_fee_status() directly "cuts" the paid amount from the
            # next unpaid installment item(s) by marking them paid sequentially.
            created_student_fees = StudentFee.objects.filter(
                student__in=[s.id for s in students_to_assign],
                fee_structure=fee_structure,
            )
            from .models import InstallmentPlan, InstallmentItem
            from django.utils import timezone
            for sf in created_student_fees:
                # Use updated get_installment_plan_status with level name
                num_items = 1  # default lumpsum; customize based on business rules
                plan_status = get_installment_plan_status(
                    getattr(fee_structure.level, 'name', ''), num_items
                )
                plan = InstallmentPlan.objects.create(
                    student_fee=sf,
                    created_by=fee_structure.created_by,
                    status=plan_status,
                )
                # One item by default (full amount); can be split into multiple via UI
                InstallmentItem.objects.create(
                    plan=plan,
                    amount=sf.total_amount,
                    due_date=timezone.now().date() + timezone.timedelta(days=30),
                    is_paid=False,
                )

        return fee_structure


# ═══════════════════════════════════════════════════════════════════════════════
#  Student Fee
# ═══════════════════════════════════════════════════════════════════════════════

class StudentFeeListSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    student_name = serializers.SerializerMethodField()
    fee_name = serializers.CharField(source='fee_structure.name', read_only=True)
    amount_due = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    course_name = serializers.SerializerMethodField()
    batch_name = serializers.SerializerMethodField()

    def get_student_name(self, obj):
        return obj.student.full_name if obj.student else ''

    def get_course_name(self, obj):
        fs_course = obj.fee_structure.course if getattr(obj, 'fee_structure', None) else None
        if fs_course:
            return fs_course.name
        return None

    def get_batch_name(self, obj):
        fs_batch = obj.fee_structure.batch
        return fs_batch.name if fs_batch else None

    class Meta:
        model = StudentFee
        fields = ['id', 'student', 'student_name', 'fee_structure', 'fee_name',
                  'total_amount', 'discount', 'amount_paid', 'amount_due',
                  'status', 'status_display', 'due_date', 'created_at',
                  'course_name', 'batch_name']


class StudentFeeDetailSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    student_email = serializers.CharField(source='student.email', read_only=True)
    fee_name = serializers.CharField(source='fee_structure.name', read_only=True)
    amount_due = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    payments = serializers.SerializerMethodField()
    installment_plans = serializers.SerializerMethodField()

    def get_student_name(self, obj):
        return obj.student.full_name if obj.student else ''

    class Meta:
        model = StudentFee
        fields = '__all__'

    def get_payments(self, obj):
        qs = obj.payments.all().order_by('-created_at')
        return PaymentListSerializer(qs, many=True).data

    def get_installment_plans(self, obj):
        qs = obj.installment_plans.all()
        return InstallmentPlanListSerializer(qs, many=True).data


class StudentFeeCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = StudentFee
        fields = ['student', 'fee_structure', 'total_amount', 'discount',
                  'discount_reason', 'due_date']

    def validate(self, data):
        discount = data.get('discount', 0) or 0
        total = data.get('total_amount', 0) or 0

        # For partial updates, use instance values if not in data
        if self.instance and not total:
            total = self.instance.total_amount
        if self.instance and 'discount' not in data:
            discount = self.instance.discount or 0

        if discount > total:
            raise serializers.ValidationError(
                {'discount': 'Discount cannot exceed total amount.'}
            )

        # Enforce one StudentFee per student (skip check on update for same student)
        student = data.get('student')
        if student:
            qs = StudentFee.objects.filter(student=student)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(
                    {'student': 'A fee record already exists for this student. Each student can only have one fee.'}
                )

        return data


# ═══════════════════════════════════════════════════════════════════════════════
#  Installment Plan
# ═══════════════════════════════════════════════════════════════════════════════

class InstallmentItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = InstallmentItem
        fields = ['id', 'amount', 'due_date', 'is_paid', 'paid_at']


class InstallmentPlanListSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    items = InstallmentItemSerializer(many=True, read_only=True)
    student_name = serializers.SerializerMethodField()

    def get_student_name(self, obj):
        if getattr(obj, 'student_fee', None) and getattr(obj.student_fee, 'student', None):
            return obj.student_fee.student.full_name
        return ''

    class Meta:
        model = InstallmentPlan
        fields = ['id', 'student_fee', 'student_name', 'status', 'status_display',
                  'approved_by', 'approved_at', 'rejection_reason',
                  'created_at', 'items']


class InstallmentPlanCreateSerializer(serializers.Serializer):
    student_fee_id = serializers.UUIDField()
    items = serializers.ListField(
        child=serializers.DictField(),
        allow_empty=False,
    )

    def validate_items(self, value):
        for item in value:
            if 'amount' not in item or 'due_date' not in item:
                raise serializers.ValidationError(
                    "Each item must have 'amount' and 'due_date'."
                )
        return value


class InstallmentPlanApproveSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=['approved', 'rejected'])
    rejection_reason = serializers.CharField(required=False, allow_blank=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  Payment
# ═══════════════════════════════════════════════════════════════════════════════

class PaymentListSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    student_name = serializers.SerializerMethodField()

    course_name = serializers.SerializerMethodField()
    batch_name = serializers.SerializerMethodField()
    payment_mode_display = serializers.CharField(source="get_payment_mode_display", read_only=True)

    def get_student_name(self, obj):
        return obj.student.full_name if obj.student else ''

    def get_course_name(self, obj):
        if getattr(obj, 'student_fee', None) and getattr(obj.student_fee, 'fee_structure', None):
            fs_course = obj.student_fee.fee_structure.course
            return fs_course.name if fs_course else None
        return None

    def get_batch_name(self, obj):
        if getattr(obj, 'student_fee', None) and getattr(obj.student_fee, 'fee_structure', None):
            fs_batch = obj.student_fee.fee_structure.batch
            return fs_batch.name if fs_batch else None
        return None

    class Meta:
        model = Payment
        fields = ['id', 'student', 'student_name', 'student_fee',
                  'installment_item', 'amount', 'payment_mode',
                  'transaction_ref', 'payment_proof', 'payment_document',
                  'status', 'status_display', 'receipt_number',
                  'payment_date', 'created_at','payment_mode_display',
                  'course_name','batch_name']
                 


class PaymentDetailSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    student_email = serializers.CharField(source='student.email', read_only=True)
    refunds = serializers.SerializerMethodField()


    payment_mode_display = serializers.CharField(source="get_payment_mode_display", read_only=True)

    def get_student_name(self, obj):
        return obj.student.full_name if obj.student else ''

    class Meta:
        model = Payment
        fields = '__all__'

    def get_refunds(self, obj):
        qs = obj.refunds.all().order_by('-created_at')
        return RefundListSerializer(qs, many=True).data


class PaymentCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = ['student', 'student_fee', 'installment_item',
                  'amount', 'payment_mode', 'transaction_ref',
                  'payment_proof', 'payment_document', 'payment_date', 'note']

    def validate_payment_proof(self, value):
        if value:
            max_size_mb = 5
            if value.size > max_size_mb * 1024 * 1024:
                raise serializers.ValidationError(
                    f"File size must be under {max_size_mb}MB."
                )
        return value

    def validate_payment_document(self, value):
        if value:
            max_size_mb = 5
            if value.size > max_size_mb * 1024 * 1024:
                raise serializers.ValidationError(
                    f"File size must be under {max_size_mb}MB."
                )
        return value

    def validate(self, data):
        student_fee = data.get('student_fee')
        amount = data.get('amount')

        if student_fee and amount:
            from django.db.models import Sum
            from decimal import Decimal
            from .models import Payment

            # Calculate the sum of pending payments
            pending_payments = Payment.objects.filter(
                student_fee=student_fee, status='approval_pending'
            ).aggregate(total=Sum('amount'))['total'] or 0
            
            pending_payments = Decimal(str(pending_payments))

            amount_due = student_fee.total_amount - student_fee.discount - student_fee.amount_paid
            remaining_to_pay = amount_due - pending_payments

            if amount > remaining_to_pay:
                raise serializers.ValidationError({
                    "amount": f"Payment amount (₹{amount}) exceeds the remaining fee due (₹{remaining_to_pay})."
                })

        return data


class PaymentVerifySerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=['verified', 'rejected'])
    note = serializers.CharField(required=False, allow_blank=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  Refund
# ═══════════════════════════════════════════════════════════════════════════════

class RefundListSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    class Meta:
        model = Refund
        fields = ['id', 'payment', 'amount', 'reason', 'status', 'status_display', 'created_at']


class RefundCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Refund
        fields = ['payment', 'amount', 'reason']

    def validate(self, data):
        payment = data.get('payment')
        amount = data.get('amount')
        if payment and amount:
            already_refunded = sum(
                r.amount for r in payment.refunds.filter(status='completed')
            )
            if amount > (payment.amount - already_refunded):
                raise serializers.ValidationError(
                    {'amount': 'Refund amount exceeds payment balance.'}
                )
        return data


# ═══════════════════════════════════════════════════════════════════════════════
#  Bank Account
# ═══════════════════════════════════════════════════════════════════════════════

class BankAccountListSerializer(serializers.ModelSerializer):
    class Meta:
        model = BankAccount
        fields = ['id', 'name', 'bank_name', 'account_number',
                  'ifsc_code', 'branch_name', 'is_active', 'max_payment_amount']


class BankAccountCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = BankAccount
        fields = ['name', 'bank_name', 'account_number',
                  'ifsc_code', 'branch_name', 'is_active']


# ═══════════════════════════════════════════════════════════════════════════════
#  Fee Report Serializer
# ═══════════════════════════════════════════════════════════════════════════════

class FeeReportSerializer(serializers.Serializer):
    """Used for the fee collection report endpoint."""
    total_billed = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_collected = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_pending = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_overdue = serializers.DecimalField(max_digits=12, decimal_places=2)
    collection_by_mode = serializers.DictField()
    monthly_trend = serializers.ListField()
