from rest_framework import serializers
from .models import (
    FeeStructure, StudentFee,
    InstallmentPlan, InstallmentItem,
    Payment, Refund, BankAccount,
    PAYMENT_MODE_CHOICES, PAYMENT_STATUS_CHOICES,
    FEE_STATUS_CHOICES, INSTALLMENT_PLAN_STATUS_CHOICES,
    REFUND_STATUS_CHOICES,
)


# ═══════════════════════════════════════════════════════════════════════════════
#  Fee Structure
# ═══════════════════════════════════════════════════════════════════════════════

class FeeStructureListSerializer(serializers.ModelSerializer):
    course_name = serializers.CharField(source='course.name', read_only=True, default=None)
    batch_name = serializers.CharField(source='batch.name', read_only=True, default=None)

    class Meta:
        model = FeeStructure
        fields = ['id', 'name', 'course', 'course_name', 'batch', 'batch_name',
                  'total_amount', 'is_active', 'created_at']


class FeeStructureDetailSerializer(serializers.ModelSerializer):
    course_name = serializers.CharField(source='course.name', read_only=True, default=None)
    batch_name = serializers.CharField(source='batch.name', read_only=True, default=None)

    class Meta:
        model = FeeStructure
        fields = '__all__'


class FeeStructureCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeeStructure
        fields = ['name', 'course', 'batch', 'total_amount', 'description', 'is_active']


# ═══════════════════════════════════════════════════════════════════════════════
#  Student Fee
# ═══════════════════════════════════════════════════════════════════════════════

class StudentFeeListSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    student_name = serializers.CharField(source='student.name', read_only=True)
    fee_name = serializers.CharField(source='fee_structure.name', read_only=True)
    amount_due = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = StudentFee
        fields = ['id', 'student', 'student_name', 'fee_structure', 'fee_name',
                  'total_amount', 'discount', 'amount_paid', 'amount_due',
                  'status', 'status_display', 'due_date', 'created_at']


class StudentFeeDetailSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source='student.name', read_only=True)
    student_email = serializers.CharField(source='student.email', read_only=True)
    fee_name = serializers.CharField(source='fee_structure.name', read_only=True)
    amount_due = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    payments = serializers.SerializerMethodField()
    installment_plans = serializers.SerializerMethodField()

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
    student_name = serializers.CharField(source='student_fee.student.name', read_only=True)

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
    student_name = serializers.CharField(source='student.name', read_only=True)

    class Meta:
        model = Payment
        fields = ['id', 'student', 'student_name', 'student_fee',
                  'installment_item', 'amount', 'payment_mode',
                  'transaction_ref', 'status', 'status_display', 'receipt_number',
                  'payment_date', 'created_at']


class PaymentDetailSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source='student.name', read_only=True)
    student_email = serializers.CharField(source='student.email', read_only=True)
    refunds = serializers.SerializerMethodField()

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
                  'payment_proof', 'payment_date', 'note']

    def validate_payment_proof(self, value):
        if value:
            max_size_mb = 5
            if value.size > max_size_mb * 1024 * 1024:
                raise serializers.ValidationError(
                    f"File size must be under {max_size_mb}MB."
                )
        return value


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
                  'ifsc_code', 'is_active']


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
