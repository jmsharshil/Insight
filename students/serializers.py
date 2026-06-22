from rest_framework import serializers

from .models import (Student,ParentLink,BatchHistory,InventoryIssue,DigitalIDCard,StudentStatusHistory,STUDENT_STATUS_CHOICES,)


class IssuedInventoryItemSerializer(serializers.Serializer):
    """Nested read-only snapshot of an inventory allocation issued to this student."""
    allocation_id = serializers.UUIDField(source='id')
    item_id = serializers.UUIDField(source='item.id')
    item_name = serializers.CharField(source='item.name')
    item_description = serializers.CharField(source='item.description')
    item_size = serializers.CharField(source='item.size')
    quantity = serializers.IntegerField()
    status = serializers.CharField()
    status_display = serializers.CharField(source='get_status_display')
    issued_at = serializers.DateTimeField()
    returned_at = serializers.DateTimeField()
    notes = serializers.CharField()

# ── Nested Micro-Serializers (read-only) ──────────────────────────────────────

class BranchInfoSerializer(serializers.Serializer):
    id   = serializers.UUIDField()
    name = serializers.CharField()
    city = serializers.CharField()


class CounsellorInfoSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    email = serializers.EmailField()
    phone = serializers.CharField()


class ParentLinkReadSerializer(serializers.ModelSerializer):
    parent_id = serializers.UUIDField(source='parent.id')
    parent_name  = serializers.CharField(source='parent.name')
    parent_email = serializers.EmailField(source='parent.email')
    parent_phone = serializers.CharField(source='parent.phone')


    relationship_display = serializers.CharField(source="get_relationship_display", read_only=True)

    class Meta:
        model  = ParentLink
        fields = [
            'id', 'relationship', 'is_primary',
            'parent_id', 'parent_name', 'parent_email', 'parent_phone',
            'linked_at',
         'relationship_display']


class BatchHistoryReadSerializer(serializers.ModelSerializer):
    changed_by_name = serializers.CharField(source='changed_by.name', default=None)

    class Meta:
        model  = BatchHistory
        fields = ['id', 'batch_name', 'reason', 'changed_by_name', 'changed_at']


class InventoryIssueReadSerializer(serializers.ModelSerializer):
    issued_by_name = serializers.CharField(source='issued_by.name', default=None)


    item_type_display = serializers.CharField(source="get_item_type_display", read_only=True)

    class Meta:
        model  = InventoryIssue
        fields = [
            'id', 'item_type', 'item_name', 'quantity', 'size', 'isbn',
            'issued_by_name', 'issued_at', 'returned_at', 'notes',
         'item_type_display']


class DigitalIDCardReadSerializer(serializers.ModelSerializer):
    class Meta:
        model  = DigitalIDCard
        fields = ['id', 'qr_data', 'qr_image', 'card_image', 'is_active', 'generated_at', 'regenerated_at']


class StudentStatusHistorySerializer(serializers.ModelSerializer):
    changed_by_name = serializers.CharField(source='changed_by.name', default=None)


    old_status_display = serializers.CharField(source="get_old_status_display", read_only=True)
    new_status_display = serializers.CharField(source="get_new_status_display", read_only=True)

    class Meta:
        model  = StudentStatusHistory
        fields = ['id', 'old_status', 'new_status', 'reason', 'changed_by_name', 'changed_at', 'old_status_display', 'new_status_display']


# ── Student List Serializer ───────────────────────────────────────────────────

class StudentListSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    """Lightweight — used for paginated list views."""
    full_name = serializers.SerializerMethodField()
    branch_name = serializers.CharField(source='branch.name', default=None)
    batch_name = serializers.CharField(source='current_batch_name', default=None)
    photo_url = serializers.SerializerMethodField()


    gender_display = serializers.CharField(source="get_gender_display", read_only=True)
    blood_group_display = serializers.CharField(source="get_blood_group_display", read_only=True)
    emergency_contact_relationship_display = serializers.CharField(source="get_emergency_contact_relationship_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model  = Student
        fields = [
            'id', 'admission_number', 'full_name', 'email', 'phone_student',
            'course', 'group_module', 'batch_attempt',
            'branch', 'branch_name', 'batch_name',
            'status', 'status_display', 'enrolled_at', 'photo_url',
            'gender_display', 'blood_group_display', 'emergency_contact_relationship_display']
        
         

    def get_full_name(self, obj):
        return obj.full_name

    def get_photo_url(self, obj):
        request = self.context.get('request')
        if obj.photo and request:
            return request.build_absolute_uri(obj.photo.url)
        return None


# ── Student Detail Serializer (admin / counsellor full view) ──────────────────

class StudentDetailSerializer(serializers.ModelSerializer):
    """Full profile — used by admin / counsellor detail endpoints."""
    full_name = serializers.SerializerMethodField()
    branch = BranchInfoSerializer(read_only=True)
    current_batch_name = serializers.CharField(read_only=True)
    assigned_counsellor = CounsellorInfoSerializer(read_only=True)
    parent_links = ParentLinkReadSerializer(many=True, read_only=True)
    batch_history = BatchHistoryReadSerializer(many=True, read_only=True)
    inventory_issues = InventoryIssueReadSerializer(many=True, read_only=True)
    id_card = DigitalIDCardReadSerializer(read_only=True)
    status_history = StudentStatusHistorySerializer(many=True, read_only=True)
    photo_url = serializers.SerializerMethodField()
    id_card_ready = serializers.BooleanField(read_only=True)
    branch_name = serializers.CharField(source='branch.name', default=None)
    issued_items = serializers.SerializerMethodField()


    gender_display = serializers.CharField(source="get_gender_display", read_only=True)
    blood_group_display = serializers.CharField(source="get_blood_group_display", read_only=True)
    emergency_contact_relationship_display = serializers.CharField(source="get_emergency_contact_relationship_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model  = Student
        fields = '__all__'

    def get_full_name(self, obj):
        return obj.full_name

    def get_issued_items(self, obj):
        try:
            from inventory.models import ItemAllocation
            allocations = ItemAllocation.objects.filter(
                student=obj
            ).select_related('item').order_by('-issued_at')
            return IssuedInventoryItemSerializer(allocations, many=True).data
        except Exception:
            return []

    def get_photo_url(self, obj):
        request = self.context.get('request')
        if obj.photo and request:
            return request.build_absolute_uri(obj.photo.url)
        return None


# ── Student Self-Profile Serializer (student mobile app view) ─────────────────

class StudentSelfProfileSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    """
    Read-only view for the student themselves.
    Excludes internal admin fields (notes, status_history, counsellor details).
    """
    full_name = serializers.SerializerMethodField()
    branch = BranchInfoSerializer(read_only=True)
    current_batch_name = serializers.CharField(read_only=True)
    parent_links = ParentLinkReadSerializer(many=True, read_only=True)
    id_card = DigitalIDCardReadSerializer(read_only=True)
    photo_url = serializers.SerializerMethodField()
    id_card_ready = serializers.BooleanField(read_only=True)


    gender_display = serializers.CharField(source="get_gender_display", read_only=True)
    blood_group_display = serializers.CharField(source="get_blood_group_display", read_only=True)
    emergency_contact_relationship_display = serializers.CharField(source="get_emergency_contact_relationship_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Student
        fields = [
            'id', 'admission_number', 'full_name',
            'first_name', 'surname', 'father_name', 'mother_name',
            'dob', 'gender', 'blood_group', 'category', 'nationality',
            'email', 'phone_student', 'phone_student_2',
            'street', 'apartment', 'city', 'state', 'pincode', 'country',
            'emergency_contact_name', 'emergency_contact_phone', 'emergency_contact_relationship',
            'course', 'group_module', 'batch_attempt', 'qualification', 'location',
            'branch', 'current_batch_name',
            'photo_url', 'status', 'status_display', 'enrolled_at',
            'parent_links', 'id_card', 'id_card_ready',
         'gender_display', 'blood_group_display', 'emergency_contact_relationship_display', 'status_display']

    def get_full_name(self, obj):
        return obj.full_name

    def get_photo_url(self, obj):
        request = self.context.get('request')
        if obj.photo and request:
            return request.build_absolute_uri(obj.photo.url)
        return None


# ── Student Update Serializer ─────────────────────────────────────────────────

class StudentUpdateSerializer(serializers.ModelSerializer):
    """
    PATCH /api/students/<id>/
    All fields optional; restricted set — core immutable fields excluded.
    """
    class Meta:
        model  = Student
        exclude = [
            'id', 'admission_number', 'admission', 'user',
            'created_at', 'enrolled_at',
        ]
        read_only_fields = ['id', 'admission_number', 'admission', 'user']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.required = False

    def validate_status(self, value):
        # Status changes via dedicated endpoint only (StudentStatusUpdateSerializer)
        raise serializers.ValidationError(
            "Use the /status/ endpoint to change student status."
        )


# ── Student Status Update Serializer ─────────────────────────────────────────

class StudentStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=STUDENT_STATUS_CHOICES)
    reason = serializers.CharField(required=False, allow_blank=True)


# ── Inventory Issue Create Serializer ─────────────────────────────────────────

class InventoryIssueCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = InventoryIssue
        fields = ['item_type', 'item_name', 'quantity', 'size', 'isbn', 'notes']

    def validate_quantity(self, value):
        if value < 1:
            raise serializers.ValidationError("Quantity must be at least 1.")
        return value


# ── Batch Allocate Serializer ─────────────────────────────────────────────────

class BatchAllocateSerializer(serializers.Serializer):
    batch_name = serializers.CharField(max_length=200)
    reason = serializers.CharField(required=False, allow_blank=True)


# ── Document Upload Serializer ────────────────────────────────────────────────

ALLOWED_DOC_TYPES = ['image/jpeg', 'image/png', 'application/pdf']
MAX_DOC_SIZE_MB   = 5

DOCUMENT_FIELD_CHOICES = [
    'doc_signature', 'doc_dob_certificate', 'doc_id_proof',
    'doc_tenth_marksheet', 'doc_twelfth_marksheet',
    'doc_category_cert', 'doc_graduation_cert', 'photo',
]


class DocumentUploadSerializer(serializers.Serializer):
    """
    POST /api/admissions/<id>/documents/
    POST /api/students/<id>/documents/
    Upload or replace a single named document on the record.
    """
    field_name = serializers.ChoiceField(choices=[(f, f) for f in DOCUMENT_FIELD_CHOICES])
    file       = serializers.FileField()

    def validate_file(self, value):
        if value.content_type not in ALLOWED_DOC_TYPES:
            raise serializers.ValidationError(
                f"Unsupported file type '{value.content_type}'. "
                f"Allowed: {', '.join(ALLOWED_DOC_TYPES)}"
            )
        max_bytes = MAX_DOC_SIZE_MB * 1024 * 1024
        if value.size > max_bytes:
            raise serializers.ValidationError(
                f"File size must be under {MAX_DOC_SIZE_MB}MB. "
                f"Uploaded: {value.size / (1024 * 1024):.1f}MB."
            )
        return value


# ── QR / ID Card Serializer ───────────────────────────────────────────────────

class QRIdentitySerializer(serializers.Serializer):
    """
    Response payload for GET /api/students/<id>/qr-id/
    Returns all data needed to render the digital ID card client-side,
    plus the raw QR payload the mobile app encodes.
    """
    student_id = serializers.UUIDField()
    admission_number = serializers.CharField()
    full_name = serializers.CharField()
    course = serializers.CharField()
    batch_name = serializers.CharField(allow_null=True)
    branch_name = serializers.CharField(allow_null=True)
    photo_url = serializers.CharField(allow_null=True)
    qr_payload = serializers.CharField()   # UUID string — scanned at check-in
    qr_image_url = serializers.CharField(allow_null=True)
    card_image_url = serializers.CharField(allow_null=True)
    generated_at = serializers.DateTimeField(allow_null=True)
    is_active = serializers.BooleanField()