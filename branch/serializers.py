from rest_framework import serializers

from .models import Branch


class BranchListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Branch
        fields = ["id", "name", "city", "logo", "is_active", "created_at"]

class BranchDetailSerializer(serializers.ModelSerializer):
    student_count = serializers.IntegerField(read_only=True)
    staff_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Branch
        fields = "__all__"


class BranchCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Branch
        fields = ["name","address","city","state","pincode","phone","email","principal_name","logo","is_active",]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].required = False


class BranchSummarySerializer(serializers.Serializer):
    total_students = serializers.IntegerField()
    active_students = serializers.IntegerField()
    total_staff = serializers.IntegerField()
    total_leads = serializers.IntegerField()
    leads_this_month = serializers.IntegerField()
    admissions_this_month = serializers.IntegerField()
    fee_collected_this_month = serializers.DecimalField(max_digits=12,decimal_places=2)
    fee_pending = serializers.DecimalField(max_digits=12,decimal_places=2)
    exams_this_month = serializers.IntegerField()
    attendance_avg_percent = serializers.FloatField()