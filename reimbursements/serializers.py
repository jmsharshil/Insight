from decimal import Decimal
from rest_framework import serializers
from .models import Reimbursement


class ReimbursementCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Reimbursement
        fields = ['id', 'title', 'description', 'amount', 'proof', 'expense_date']
        read_only_fields = ['id']

    def validate_amount(self, value):
        if value <= Decimal('0'):
            raise serializers.ValidationError("Amount must be greater than zero.")
        return value

    def create(self, validated_data):
        request = self.context.get('request')
        user = request.user if request else validated_data.get('user')
        branch = getattr(user, 'branch', None)
        validated_data['user'] = user
        if branch and 'branch' not in validated_data:
            validated_data['branch'] = branch
        return super().create(validated_data)


class ReimbursementUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Reimbursement
        fields = ['title', 'description', 'amount', 'proof', 'expense_date']

    def validate_amount(self, value):
        if value <= Decimal('0'):
            raise serializers.ValidationError("Amount must be greater than zero.")
        return value

    def validate(self, attrs):
        if self.instance.status != 'pending':
            raise serializers.ValidationError("Cannot modify a reimbursement that has already been reviewed.")
        return attrs


class ReimbursementSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.name', read_only=True)
    user_email = serializers.CharField(source='user.email', read_only=True)
    user_role = serializers.CharField(source='user.role', read_only=True)
    branch_name = serializers.CharField(source='branch.name', default=None, read_only=True)
    approved_by_name = serializers.CharField(source='approved_by.name', default=None, read_only=True)
    rejected_by_name = serializers.CharField(source='rejected_by.name', default=None, read_only=True)
    payroll_month = serializers.IntegerField(source='payroll_run.month', default=None, read_only=True)
    payroll_year = serializers.IntegerField(source='payroll_run.year', default=None, read_only=True)

    class Meta:
        model = Reimbursement
        fields = [
            'id', 'user', 'user_name', 'user_email', 'user_role',
            'branch', 'branch_name', 'title', 'description', 'amount',
            'proof', 'expense_date', 'status',
            'approved_by', 'approved_by_name', 'approved_at',
            'rejected_by', 'rejected_by_name', 'rejected_at', 'rejection_reason',
            'payroll_run', 'payroll_month', 'payroll_year', 'payslip', 'is_paid',
            'created_at', 'updated_at'
        ]
        read_only_fields = fields


class ReimbursementRejectSerializer(serializers.Serializer):
    rejection_reason = serializers.CharField(required=True, allow_blank=False, max_length=500)
