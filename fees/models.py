from django.db import models
from django.conf import settings
import uuid
from leads.models import ATTEMPT_TYPE_CHOICES, GROUP_MODULE_CHOICES

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
    name        = models.CharField(max_length=200, blank=True)
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
    syllabus    = models.ForeignKey(
        'batches.Syllabus', on_delete=models.SET_NULL,
        related_name='fee_structures', null=True, blank=True,
        verbose_name='Syllabus'
    )
    attempt     = models.CharField(max_length=10, choices=ATTEMPT_TYPE_CHOICES, blank=True,null=True)
    # Only for CS Executive / CS Professional
    group_module = models.CharField(max_length=20, choices=GROUP_MODULE_CHOICES, blank=True,null=True)
    year        = models.PositiveSmallIntegerField(null=True, blank=True)
    total_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text='Auto-calculated as sum of components below'
    )
    # Fee type breakdown (total_amount is auto-calculated as sum of these)
    icsi_registration_fees = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        verbose_name='ICSI Registration Fees'
    )
    icsi_exam_fees = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        verbose_name='ICSI Exam Fees'
    )
    token_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        verbose_name='Token Amount'
    )
    icsi_registration_fees_via_cseet = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        verbose_name='ICSI Registration Fees via CSEET'
    )
    icsi_registration_fees_direct = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        verbose_name='ICSI Registration Fees Direct'
    )
    institute_fees_all_modules = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        verbose_name='Institute Fees for All Modules'
    )
    institute_fees_module_1 = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        verbose_name='Institute Fees for Module 1'
    )
    institute_fees_module_2 = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        verbose_name='Institute Fees for Module 2'
    )
    institute_fees_module_3 = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        verbose_name='Institute Fees for Module 3'
    )
    institute_fees_module_4 = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        verbose_name='Institute Fees for Module 4'
    )
    institute_fees_module_5 = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        verbose_name='Institute Fees for Module 5'
    )
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

    @property
    def modules_count(self):
        """Count of active modules belonging to this fee structure's syllabus."""
        if self.syllabus_id and self.syllabus:
            return self.syllabus.modules.filter(is_active=True).count()
        return 0

    @property
    def syllabus_modules(self):
        """List of active module summaries for this fee structure's syllabus."""
        if self.syllabus_id and self.syllabus:
            return list(self.syllabus.modules.filter(is_active=True).order_by('order', 'name').values('id', 'name', 'order', 'description'))
        return []

    def save(self, *args, **kwargs):
        # Auto-sync level and course from syllabus if missing
        if self.syllabus_id and self.syllabus:
            if not self.level_id and self.syllabus.level_id:
                self.level = self.syllabus.level
            if not self.course_id and self.syllabus.level and self.syllabus.level.course_id:
                self.course = self.syllabus.level.course

        # Auto-sync course from level if missing
        if not self.course_id and self.level_id and self.level:
            self.course = self.level.course

        # Auto-generate name if not explicitly provided (matching Batch name logic)
        if not self.name:
            from django.utils import timezone

            # Resolve year
            year = self.year
            if not year and self.batch_id and self.batch:
                year = getattr(self.batch, 'attempt_year', None) or (self.batch.start_date.year if self.batch.start_date else None)
            if not year and self.attempt:
                try:
                    from batches.services import get_exam_attempt_year
                    course_type_for_year = 'cseet'
                    if self.level_id and self.level and self.level.name:
                        course_type_for_year = self.level.name.strip().replace(' ', '_').lower()
                    elif self.course_id and self.course:
                        course_type_for_year = getattr(self.course, 'course_type', None) or 'cseet'
                    year = get_exam_attempt_year(
                        course=course_type_for_year,
                        batch_attempt=self.attempt,
                        group_module=self.group_module or '',
                        form_date=timezone.now().date(),
                    )
                except Exception:
                    year = timezone.now().year
            if not year:
                year = timezone.now().year

            if not self.year:
                self.year = year

            # Resolve course_type
            course_type = None
            if self.level_id and self.level and self.level.name:
                course_type = self.level.name.strip().replace(' ', '_')
            if not course_type and self.course:
                course_type = getattr(self.course, 'course_type', None)
            if not course_type and self.course:
                first_level = self.course.levels.filter(is_active=True).first()
                if first_level:
                    course_type = first_level.name.strip().replace(' ', '_')
            if not course_type and self.course and self.course.name:
                course_type = self.course.name.strip().replace(' ', '_')
            if not course_type and self.batch_id and self.batch and self.batch.course:
                course_type = getattr(self.batch.course, 'course_type', None) or self.batch.course.name.strip().replace(' ', '_')
            if not course_type:
                course_type = 'standard'

            # Group module & attempt
            group_module = (self.group_module or (self.batch.group_module if self.batch_id and self.batch else '')) or ''
            attempt = (self.attempt or (self.batch.batch_attempt if self.batch_id and self.batch else '')) or ''

            # Branch (if batch has branch or created_by has branch)
            branch = None
            if self.batch_id and self.batch and self.batch.branch:
                branch = self.batch.branch
            elif self.created_by_id and hasattr(self.created_by, 'branch') and self.created_by.branch:
                branch = self.created_by.branch

            branch_prefix = ''
            if branch and getattr(branch, 'name', None):
                try:
                    parts = branch.name.split('-')
                    if len(parts) >= 2:
                        bseq = parts[-1]
                        branch_prefix = f"{bseq.lstrip('0') or '0'}".upper()
                    else:
                        branch_prefix = f"{branch.name[:4]}".upper()
                except Exception:
                    branch_prefix = 'BXX'

            ct_upper = str(course_type).upper() if course_type else ""
            attempt_upper = str(attempt).upper() if attempt and attempt.lower() != 'unknown' else ""
            year_str = str(year)[-2:] if year else ""
            gm_upper = str(group_module).upper() if group_module else ""
            branch_prefix = branch_prefix.strip()

            base_parts = [branch_prefix, ct_upper, attempt_upper, year_str, gm_upper]
            base_prefix = '_'.join(p for p in base_parts if p)

            # Use base_prefix directly as the name (no sequence number suffix).
            # Only add a numeric suffix (_2, _3, ...) if the name already exists.
            candidate_name = base_prefix if base_prefix else 'FEE'
            if FeeStructure.objects.filter(name=candidate_name).exclude(pk=self.pk).exists():
                suffix = 2
                while FeeStructure.objects.filter(name=f"{candidate_name}_{suffix}").exclude(pk=self.pk).exists():
                    suffix += 1
                candidate_name = f"{candidate_name}_{suffix}"

            self.name = candidate_name

        super().save(*args, **kwargs)


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
    m_id      = models.CharField(max_length=100, blank=True, null=True, help_text="UPI ID for generating UPI payment links")
    razorpay_account_id = models.CharField(max_length=100, blank=True, null=True, help_text="Razorpay Linked Account ID (e.g. acc_...) for Route transfers")
    is_active   = models.BooleanField(default=True)
    max_payment_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = 'bank_accounts'
        ordering  = ['name']
        indexes = [
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
        return f"{self.name} — {self.bank_name} ({self.account_number})"

    def is_under_threshold(self, amount):
        """Return True if the sum of verified payments in the current financial year plus amount is <= max_payment_amount."""
        if self.max_payment_amount is None:
            return True
            
        from django.utils import timezone
        from .models import Payment
        from django.db.models import Sum
        from decimal import Decimal
        
        now = timezone.now()
        if now.month >= 4:
            start_date = now.replace(month=4, day=1, hour=0, minute=0, second=0, microsecond=0)
            end_date = now.replace(year=now.year + 1, month=4, day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            start_date = now.replace(year=now.year - 1, month=4, day=1, hour=0, minute=0, second=0, microsecond=0)
            end_date = now.replace(month=4, day=1, hour=0, minute=0, second=0, microsecond=0)
            
        total_paid = Payment.objects.filter(
            student__admission__bank_account=self,
            payment_date__gte=start_date.date(),
            payment_date__lt=end_date.date(),
            status='verified'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
        
        return (Decimal(total_paid) + Decimal(amount)) <= self.max_payment_amount
