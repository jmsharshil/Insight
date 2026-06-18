from django.db import models
from django.conf import settings
import uuid


# ── Choice constants ────────────────────────────────────────────────────────────
PAYMENT_MODE_CHOICES = [
    ('cash',    'Cash'),
    ('online',  'Online Transfer'),
    ('cheque',  'Cheque'),
    ('dd',      'Demand Draft'),
    ('upi',     'UPI'),
]

PAYMENT_STATUS_CHOICES = [
    ('approval_pending', 'Approval Pending'),
    ('verified', 'Verified'),
    ('rejected', 'Rejected'),
]

FEE_STATUS_CHOICES = [
    ('approval_pending', 'Approval Pending'),
    ('partial', 'Partial'),
    ('paid',    'Paid'),
    ('overdue', 'Overdue'),
]

INSTALLMENT_PLAN_STATUS_CHOICES = [
    ('pending_approval', 'Pending Approval'),
    ('approved',        'Approved'),
    ('rejected',        'Rejected'),
    ('active',          'Active'),
    ('completed',       'Completed'),
]

REFUND_STATUS_CHOICES = [
    ('approval_pending', 'Approval Pending'),
    ('completed', 'Completed'),
    ('rejected',  'Rejected'),
]


# ═══════════════════════════════════════════════════════════════════════════════
#  Fee Structure
# ═══════════════════════════════════════════════════════════════════════════════

class FeeStructure(models.Model):
    """Defines the fee for a particular course/batch."""
    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name        = models.CharField(max_length=200)
    course      = models.ForeignKey(
        'batches.Course', on_delete=models.CASCADE,
        related_name='fee_structures', null=True, blank=True,
    )
    batch       = models.ForeignKey(
        'batches.Batch', on_delete=models.CASCADE,
        related_name='fee_structures', null=True, blank=True,
    )
    level       = models.ForeignKey(
        'batches.CourseLevel', on_delete=models.CASCADE,
        related_name='fee_structures', null=True, blank=True,
    )
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.TextField(blank=True)
    is_active   = models.BooleanField(default=True)
    created_by  = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='created_fee_structures',
    )
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        db_table  = 'fee_structures'
        ordering  = ['-created_at']
        indexes = [
            models.Index(fields=['course', 'is_active']),
            models.Index(fields=['batch', 'is_active']),
        ]

    def __str__(self):
        return f"{self.name} — ₹{self.total_amount}"


# ═══════════════════════════════════════════════════════════════════════════════
#  Student Fee (instance of a fee structure applied to a student)
# ═══════════════════════════════════════════════════════════════════════════════

class StudentFee(models.Model):
    """Links a student to a fee structure with computed amounts."""
    id             = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student        = models.ForeignKey(
        'students.Student', on_delete=models.CASCADE,
        related_name='student_fees',
    )
    fee_structure  = models.ForeignKey(
        FeeStructure, on_delete=models.CASCADE,
        related_name='student_fees',
    )
    total_amount   = models.DecimalField(max_digits=10, decimal_places=2)
    discount       = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount_reason = models.CharField(max_length=255, blank=True)
    amount_paid    = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    status         = models.CharField(max_length=20, choices=FEE_STATUS_CHOICES, default='approval_pending')
    due_date       = models.DateField(null=True, blank=True)
    created_at     = models.DateTimeField(auto_now_add=True)
    updated_at     = models.DateTimeField(auto_now=True)

    class Meta:
        db_table  = 'student_fees'
        ordering  = ['-created_at']
        indexes   = [
            models.Index(fields=['student', 'status']),
            models.Index(fields=['status', 'due_date']),
            models.Index(fields=['-created_at']),
        ]

    def __str__(self):
        return f"{self.student.full_name} — {self.fee_structure.name} — {self.status}"

    @property
    def amount_due(self):
        return self.total_amount - self.discount - self.amount_paid


# ═══════════════════════════════════════════════════════════════════════════════
#  Installment Plan & Items
# ═══════════════════════════════════════════════════════════════════════════════

class InstallmentPlan(models.Model):
    id               = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student_fee      = models.ForeignKey(
        StudentFee, on_delete=models.CASCADE,
        related_name='installment_plans',
    )
    created_by       = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='created_installment_plans',
    )
    status           = models.CharField(
        max_length=20, choices=INSTALLMENT_PLAN_STATUS_CHOICES,
        default='pending_approval',
    )
    approved_by      = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='approved_installment_plans',
    )
    approved_at      = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.CharField(max_length=255, blank=True)
    created_at       = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = 'installment_plans'
        ordering  = ['-created_at']
        indexes = [
            models.Index(fields=['student_fee', 'status']),
            models.Index(fields=['-created_at']),
        ]

    def __str__(self):
        return f"Plan for {self.student_fee} — {self.status}"


class InstallmentItem(models.Model):
    id       = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plan     = models.ForeignKey(
        InstallmentPlan, on_delete=models.CASCADE,
        related_name='items',
    )
    amount   = models.DecimalField(max_digits=10, decimal_places=2)
    due_date = models.DateField()
    is_paid  = models.BooleanField(default=False)
    paid_at  = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table  = 'installment_items'
        ordering  = ['due_date']
        indexes = [
            models.Index(fields=['plan', 'is_paid']),
            models.Index(fields=['due_date', 'is_paid']),
        ]

    def __str__(self):
        return f"{self.plan} — ₹{self.amount} due {self.due_date}"


# ═══════════════════════════════════════════════════════════════════════════════
#  Payment
# ═══════════════════════════════════════════════════════════════════════════════

def generate_receipt_number():
    """Auto-generate a unique receipt number: RCT-{YYYY}{MM}-{seq}."""
    from django.utils import timezone
    now = timezone.now()
    prefix = f"RCT-{now.strftime('%Y%m')}"
    last = Payment.objects.filter(
        receipt_number__startswith=prefix
    ).order_by('-receipt_number').first()
    if last and last.receipt_number:
        try:
            seq = int(last.receipt_number.split('-')[-1]) + 1
        except (ValueError, IndexError):
            seq = 1
    else:
        seq = 1
    return f"{prefix}-{seq:04d}"


class Payment(models.Model):
    id                = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student           = models.ForeignKey(
        'students.Student', on_delete=models.CASCADE,
        related_name='payments',
    )
    student_fee       = models.ForeignKey(
        StudentFee, on_delete=models.CASCADE,
        related_name='payments',
    )
    installment_item  = models.ForeignKey(
        InstallmentItem, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='payments',
    )
    amount            = models.DecimalField(max_digits=10, decimal_places=2)
    payment_mode      = models.CharField(max_length=20, choices=PAYMENT_MODE_CHOICES)
    transaction_ref   = models.CharField(max_length=100, blank=True)
    payment_proof     = models.FileField(
        upload_to='payments/proofs/', null=True, blank=True,
    )
    payment_document  = models.FileField(
        upload_to='payments/documents/', null=True, blank=True,
    )
    status            = models.CharField(
        max_length=20, choices=PAYMENT_STATUS_CHOICES, default='approval_pending',
    )
    receipt_number    = models.CharField(
        max_length=50, unique=True, blank=True,
    )
    recorded_by       = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='recorded_payments',
    )
    verified_by       = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='verified_payments',
    )
    verified_at       = models.DateTimeField(null=True, blank=True)
    payment_date      = models.DateField()
    note              = models.TextField(blank=True)
    created_at        = models.DateTimeField(auto_now_add=True)
    updated_at        = models.DateTimeField(auto_now=True)

    class Meta:
        db_table  = 'payments'
        ordering  = ['-created_at']
        indexes   = [
            models.Index(fields=['student', 'status']),
            models.Index(fields=['payment_date']),
            models.Index(fields=['receipt_number']),
            models.Index(fields=['status', 'payment_date']),
            models.Index(fields=['student_fee', 'status']),
        ]

    def __str__(self):
        return f"{self.receipt_number} — {self.student.full_name} — ₹{self.amount}"

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        old_status = None
        if not is_new:
            try:
                old_status = Payment.objects.get(pk=self.pk).status
            except Payment.DoesNotExist:
                old_status = None
        
        if not self.receipt_number:
            self.receipt_number = generate_receipt_number()
        super().save(*args, **kwargs)
        
        # Auto-update student fee status when payment is created or status changes
        if self.student_fee_id:
            from fees.utils import update_student_fee_status
            update_student_fee_status(self.student_fee_id)


# ═══════════════════════════════════════════════════════════════════════════════
#  Refund
# ═══════════════════════════════════════════════════════════════════════════════

class Refund(models.Model):
    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payment       = models.ForeignKey(
        Payment, on_delete=models.CASCADE,
        related_name='refunds',
    )
    amount        = models.DecimalField(max_digits=10, decimal_places=2)
    reason        = models.TextField()
    processed_by  = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='processed_refunds',
    )
    status        = models.CharField(
        max_length=20, choices=REFUND_STATUS_CHOICES, default='approval_pending',
    )
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = 'refunds'
        ordering  = ['-created_at']
        indexes = [
            models.Index(fields=['payment', 'status']),
            models.Index(fields=['-created_at']),
        ]

    def __str__(self):
        return f"Refund ₹{self.amount} for {self.payment.receipt_number} — {self.status}"


# ═══════════════════════════════════════════════════════════════════════════════
#  Bank Account (for fee category mapping)
# ═══════════════════════════════════════════════════════════════════════════════

class BankAccount(models.Model):
    """Bank accounts that can be mapped to fee structures for payment tracking."""
    id               = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name        = models.CharField(max_length=200)
    bank_name   = models.CharField(max_length=200)
    account_number = models.CharField(max_length=50)
    ifsc_code   = models.CharField(max_length=15)
    branch_name = models.CharField(max_length=200, blank=True)
    is_active   = models.BooleanField(default=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = 'bank_accounts'
        ordering  = ['name']
        indexes = [
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
        return f"{self.name} — {self.bank_name} ({self.account_number})"
