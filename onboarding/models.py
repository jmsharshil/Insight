from decimal import Decimal
from django.db import models
from django.conf import settings


# ── Re-use choice constants from leads (or duplicate them here if leads app is separate) ──
from leads.models import (
    COURSE_TYPE_CHOICES,
    GROUP_MODULE_CHOICES,
    ATTEMPT_TYPE_CHOICES,
    QUALIFICATION_TYPE_CHOICES,
    BOARD_TYPE_CHOICES,
    CATEGORY_TYPE_CHOICES,
    REFERENCE_TYPE_CHOICES,
)

ADMISSION_STATUS_CHOICES = [
    ('form_pending',      'Form Pending'),
    ('payment_pending',   'Payment Pending'),
    ('payment_submitted', 'Payment Submitted'),
    ('rejected',          'Rejected'),
    ('enrolled',          'Enrolled'),
    ('approval_pending',  'Approval Pending'),
    ('approved',          'Approved'),
]

PAYMENT_TYPE_CHOICES = [
    ('full_payment', 'Full Payment'),
    ('token', 'Token Payment'),
    ('finance', 'Finance'),
]

PAYMENT_CHOICE_CHOICES = [
    ('online', 'Online'),
    ('cash',   'Cash'),
    ('cheque', 'Cheque'),
]

ICSI_FEES_PAYMENT_CHOICES = [
    ('pay_yourself', 'Pay Yourself'),
    ('pay_through_institute', 'Pay through Institute'),
]

GENDER_CHOICES = [
    ('male', 'Male'),
    ('female', 'Female'),
    ('other', 'Other'),
]

# ── 5 Bank Accounts (round-robin assignment) ─────────────────────────────────
BANK_ACCOUNTS = [
    {
        'id': 1,
        'bank_name': 'State Bank of India (SBI)',
        'account_holder': 'Insight Institute Pvt. Ltd.',
        'account_number': '38976542103',
        'ifsc_code': 'SBIN0001234',
        'branch': 'Ashram Road, Ahmedabad',
        'account_type': 'Current Account',
    },
    {
        'id': 2,
        'bank_name': 'HDFC Bank',
        'account_holder': 'Insight Institute Pvt. Ltd.',
        'account_number': '50200045678901',
        'ifsc_code': 'HDFC0000567',
        'branch': 'CG Road, Ahmedabad',
        'account_type': 'Current Account',
    },
    {
        'id': 3,
        'bank_name': 'ICICI Bank',
        'account_holder': 'Insight Institute Pvt. Ltd.',
        'account_number': '123405001234',
        'ifsc_code': 'ICIC0003456',
        'branch': 'Navrangpura, Ahmedabad',
        'account_type': 'Current Account',
    },
    {
        'id': 4,
        'bank_name': 'Bank of Baroda',
        'account_holder': 'Insight Institute Pvt. Ltd.',
        'account_number': '21340100045678',
        'ifsc_code': 'BARB0AHMEDA',
        'branch': 'Law Garden, Ahmedabad',
        'account_type': 'Current Account',
    },
    {
        'id': 5,
        'bank_name': 'Kotak Mahindra Bank',
        'account_holder': 'Insight Institute Pvt. Ltd.',
        'account_number': '9876543210012',
        'ifsc_code': 'KKBK0007890',
        'branch': 'Prahlad Nagar, Ahmedabad',
        'account_type': 'Current Account',
    },
]


def admission_document_path(instance, filename):
    """All admission documents stored under admissions/<id>/documents/"""
    return f"onboarding/media/{instance.id}/documents/{filename}"


class Admission(models.Model):

    # ── Optional back-link to a Lead ──────────────────────────────────────────
    # If the student had previously submitted an inquiry, link it here.
    lead = models.OneToOneField(
        'leads.Lead',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='admission',
        help_text="The inquiry lead this admission originated from, if any.",
    )

    # ── Branch Scope ──────────────────────────────────────────────────────────
    branch = models.ForeignKey('branch.Branch',null=True,blank=True,on_delete=models.SET_NULL,related_name='admissions',)

    # ── Personal Info ─────────────────────────────────────────────────────────
    first_name      = models.CharField(max_length=100)
    surname         = models.CharField(max_length=100, blank=True, null=True)
    father_name     = models.CharField(max_length=100, blank=True, null=True)
    mother_name     = models.CharField(max_length=100, blank=True, null=True)
    dob             = models.DateField(blank=True,null=True)
    gender          = models.CharField(max_length=10, choices=GENDER_CHOICES, blank=True, null=True)
    category        = models.CharField(max_length=10, choices=CATEGORY_TYPE_CHOICES, blank=True, null=True)

    # ── Contact ───────────────────────────────────────────────────────────────
    email           = models.EmailField(blank=True, null=True)
    email_parent    = models.EmailField(blank=True, null=True)
    phone_student   = models.CharField(max_length=15)
    phone_student_2 = models.CharField(max_length=15, blank=True)
    phone_father    = models.CharField(max_length=15, blank=True, null=True)
    phone_father_2  = models.CharField(max_length=15, blank=True)

    # ── Address ───────────────────────────────────────────────────────────────
    street    = models.TextField(blank=True, null=True)
    apartment = models.CharField(max_length=100, blank=True)
    city      = models.CharField(max_length=100, blank=True, null=True)
    state     = models.CharField(max_length=100, blank=True, null=True)
    pincode   = models.CharField(max_length=10, blank=True, null=True)
    country   = models.CharField(max_length=100, default='India', blank=True, null=True)

    # ── Course Details ────────────────────────────────────────────────────────
    course        = models.CharField(max_length=20, choices=COURSE_TYPE_CHOICES, blank=True, null=True)
    group_module  = models.CharField(max_length=20, choices=GROUP_MODULE_CHOICES, blank=True, null=True)
    batch_attempt = models.CharField(max_length=10, choices=ATTEMPT_TYPE_CHOICES, blank=True, null=True)
    location      = models.CharField(max_length=100, blank=True, null=True)

    # ── Qualification & Reference ─────────────────────────────────────────────
    qualification = models.CharField(max_length=20, choices=QUALIFICATION_TYPE_CHOICES, blank=True, null=True)
    reference     = models.CharField(max_length=20, choices=REFERENCE_TYPE_CHOICES, blank=True, null=True)
    consent       = models.BooleanField(default=False)
    reference_name = models.CharField(max_length=100,blank=True)

    # ── 10th Education ────────────────────────────────────────────────────────
    tenth_medium     = models.CharField(max_length=10, choices=BOARD_TYPE_CHOICES, blank=True, null=True)
    tenth_school     = models.CharField(max_length=200, blank=True, null=True)
    tenth_coaching   = models.CharField(max_length=200, blank=True)
    tenth_percentage = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    tenth_percentile = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)

    # ── 12th Education ────────────────────────────────────────────────────────
    twelfth_medium     = models.CharField(max_length=10, choices=BOARD_TYPE_CHOICES, blank=True, null=True)
    twelfth_school     = models.CharField(max_length=200, blank=True, null=True)
    twelfth_coaching   = models.CharField(max_length=200, blank=True)
    twelfth_percentage = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    twelfth_percentile = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)

    # ── Graduation ────────────────────────────────────────────────────────────
    grad_university = models.CharField(max_length=200, blank=True)
    grad_college    = models.CharField(max_length=200, blank=True)
    grad_last_sem   = models.CharField(max_length=200, blank=True)

    # ── Documents (Required) ──────────────────────────────────────────────────
    doc_signature       = models.FileField(upload_to=admission_document_path, blank=True, null=True)
    doc_photo           = models.FileField(upload_to=admission_document_path, blank=True, null=True)
    doc_dob_certificate = models.FileField(upload_to=admission_document_path, blank=True, null=True)
    doc_id_card         = models.FileField(upload_to=admission_document_path, blank=True, null=True)

    # ── Documents (Optional) ──────────────────────────────────────────────────
    doc_tenth_marksheet   = models.FileField(upload_to=admission_document_path, null=True, blank=True)
    doc_twelfth_receipt   = models.FileField(upload_to=admission_document_path, null=True, blank=True)
    doc_twelfth_marksheet = models.FileField(upload_to=admission_document_path, null=True, blank=True)
    doc_category_cert     = models.FileField(upload_to=admission_document_path, null=True, blank=True)
    doc_pan_card          = models.FileField(upload_to=admission_document_path, null=True, blank=True)

    # ── Counsellor Assignment ─────────────────────────────────────────────────
    assigned_counsellor = models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name='assigned_admissions',limit_choices_to={'role': 'counsellor'},help_text="Counsellor assigned to review this admission.",)

    # ── Batch Attempt Year (for auto batch assignment) ───────────────────────
    attempt_year  = models.PositiveSmallIntegerField(null=True, blank=True)
    fee_structure = models.ForeignKey(
        'fees.FeeStructure',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='admissions',
    )
    
    # ── Payment Options ───────────────────────────────────────────────────────
    payment_type = models.CharField(max_length=20, choices=PAYMENT_TYPE_CHOICES, blank=True, null=True)
    payment_choice = models.CharField(max_length=20, choices=PAYMENT_CHOICE_CHOICES, blank=True, null=True, help_text="Choice of payment method: online, cash, or cheque.")
    icsi_fees_payment = models.CharField(max_length=30, choices=ICSI_FEES_PAYMENT_CHOICES, blank=True, null=True)

    # ── Status & Timestamps ───────────────────────────────────────────────────
    status       = models.CharField(max_length=20, choices=ADMISSION_STATUS_CHOICES, default='form_pending')
    note         = models.TextField(blank=True, help_text="Latest note added during status update.")
    submitted_at = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)
    
    #Razor Pay
    razorpay_payment_link = models.URLField(blank=True, null=True)
    razorpay_payment_link_id = models.CharField(max_length=100, blank=True, null=True)
    razorpay_payment_id = models.CharField(max_length=100, blank=True, null=True)
    
    # ── Fee Payment Tracking ──────────────────────────────────────────────────
    bank_account = models.ForeignKey(
        'fees.BankAccount',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='admissions',
        help_text="Bank account assigned for this admission's fee payment (threshold-aware selection).",
    )
    payment_screenshot    = models.FileField(upload_to=admission_document_path, null=True, blank=True)
    transaction_id        = models.CharField(max_length=100, blank=True, help_text="UPI / Bank transaction reference number.")
    payment_note          = models.TextField(blank=True, help_text="Optional note from student regarding payment.")
    payment_submitted_at  = models.DateTimeField(null=True, blank=True)
    payment_amount        = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Amount paid by the student.")
    payment_history       = models.JSONField(default=list, blank=True, help_text="Audit trail of payment links sent, payment attempts, and payments received.")

    class Meta:
        db_table = 'admissions'
        ordering = ['-submitted_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['course']),
            models.Index(fields=['submitted_at']),
            models.Index(fields=['bank_account']),
        ]

    def __str__(self):
        return f"{self.first_name} {self.surname} | {self.course} | {self.status}"

    def save(self, *args, **kwargs):
        if self.payment_choice == 'check':
            self.payment_choice = 'cheque'
        super().save(*args, **kwargs)

    def get_payment_choice_display(self):
        pc = self.payment_choice
        if pc in ('cheque', 'check'):
            return 'Cheque'
        return dict(PAYMENT_CHOICE_CHOICES).get(pc, str(pc).title() if pc else 'N/A')

    def assign_payment_bank_account(self, bank_account, *, status='payment_pending', note='Form submitted. Waiting for fee payment.'):
        """Assign a bank account only once so subsequent updates keep the original selection."""
        if self.bank_account:
            return False

        self.bank_account = bank_account
        self.status = status
        self.note = note
        self.save(update_fields=['bank_account', 'status', 'note', 'updated_at'])
        return True

    @property
    def is_paid(self):
        """Returns True if user has paid fee (via Razorpay or verified payment in Student Fees)."""
        if bool(self.razorpay_payment_id):
            return True
        if hasattr(self, 'student_profile') and self.student_profile:
            try:
                from fees.models import Payment
                if Payment.objects.filter(student=self.student_profile, status='verified').exists():
                    return True
                if Payment.objects.filter(student=self.student_profile).exists():
                    return False
            except Exception:
                pass
        if self.payment_choice in ('cash', 'cheque', 'check'):
            history = self.payment_history or []
            return any(entry.get('event') in ('payment_approved', 'payment_verified') for entry in history)
        if self.status in ('enrolled', 'approved') and (self.payment_amount or self.payment_submitted_at or self.transaction_id):
            return True
        return False

    @property
    def is_razorpay_paid(self):
        """Returns True if user made the payment via Razorpay payment link."""
        return bool(self.razorpay_payment_id)

    @property
    def razorpay_payment_status(self):
        """Status of Razorpay payment link: 'paid', 'pending', or 'not_created'."""
        if self.is_razorpay_paid:
            return 'paid'
        if self.razorpay_payment_link:
            return 'pending'
        return 'not_created'

    @property
    def total_fees(self):
        """Total fees defined for this admission based on fee structure and module."""
        if self.fee_structure:
            from onboarding.views import _get_module_fee
            return _get_module_fee(self.fee_structure, self.group_module)
        return Decimal('0')

    @property
    def remaining_fees(self):
        """
        Calculates remaining fee from total fees.
        """
        if not self.fee_structure:
            return Decimal('0')

        from onboarding.views import _get_module_fee
        total_fee = _get_module_fee(self.fee_structure, self.group_module)

        if hasattr(self, 'student_profile') and self.student_profile:
            try:
                from fees.models import Payment
                from django.db.models import Sum
                total_verified = Payment.objects.filter(
                    student=self.student_profile, status='verified'
                ).aggregate(total=Sum('amount'))['total']
                if total_verified is not None:
                    return max(Decimal('0'), total_fee - Decimal(str(total_verified)))
            except Exception:
                pass

        if self.payment_type == 'token':
            token_paid = Decimal(str(self.payment_amount or self.fee_structure.token_amount or 0))
            return max(Decimal('0'), total_fee - token_paid)

        if self.is_paid:
            paid = Decimal(str(self.payment_amount or total_fee))
            return max(Decimal('0'), total_fee - paid)
        elif self.payment_amount:
            paid = Decimal(str(self.payment_amount))
            return max(Decimal('0'), total_fee - paid)
        else:
            return total_fee

    @property
    def token_payment_terms_note(self):
        """
        Notice for token payment: remaining fees must be paid in 15 days or considered as finance.
        """
        if self.payment_type == 'token':
            remaining = self.remaining_fees
            if remaining > 0:
                return f"In 15 days you have to pay remaining fees (₹{float(remaining):,.0f}) otherwise it will be considered as Finance."
            return "In 15 days you have to pay remaining fees otherwise it will be considered as Finance."
        return None

    def add_payment_history_entry(self, event: str, data: dict):
        """Appends an event entry to payment_history and persists it."""
        from django.utils import timezone
        entry = {
            'event': event,
            'timestamp': timezone.now().isoformat(),
            **data
        }
        history = list(self.payment_history or [])
        history.append(entry)
        self.payment_history = history
        self.save(update_fields=['payment_history', 'updated_at'])

    def get_payment_history_list(self, request=None):
        """
        Returns full payment_history list including link sent events, payment transactions,
        fee breakdown (token/full_payment/finance), proof screenshots, and dates.
        """
        history = [dict(item) for item in (self.payment_history or [])]

        proof_url = None
        if self.payment_screenshot:
            try:
                raw_url = self.payment_screenshot.url
                proof_url = request.build_absolute_uri(raw_url) if request else raw_url
            except Exception:
                proof_url = str(self.payment_screenshot)

        # If payment link was generated but missing from history, synthesize it
        has_link_entry = any(item.get('event') == 'payment_link_created' for item in history)
        if not has_link_entry and self.razorpay_payment_link:
            history.insert(0, {
                'event': 'payment_link_created',
                'payment_choice': self.payment_choice or 'online',
                'amount': float(self.payment_amount or self.total_fees or 0),
                'razorpay_payment_link': self.razorpay_payment_link,
                'razorpay_payment_link_id': self.razorpay_payment_link_id,
                'status': 'paid' if self.is_razorpay_paid else 'pending',
                'created_at': self.submitted_at.isoformat() if self.submitted_at else None,
                'date': self.submitted_at.date().isoformat() if self.submitted_at else None,
            })

        # If offline choice was made without link, synthesize offline_payment_selected if history is empty
        if not history and self.payment_choice in ('cash', 'cheque', 'check'):
            history.append({
                'event': 'offline_payment_selected',
                'payment_choice': self.payment_choice,
                'amount_to_pay': float(self.total_fees or 0),
                'status': 'payment_pending',
                'created_at': self.submitted_at.isoformat() if self.submitted_at else None,
                'date': self.submitted_at.date().isoformat() if self.submitted_at else None,
                'payment_screenshot': proof_url,
                'payment_proof': proof_url,
                'transaction_id': self.transaction_id or None,
            })

        # Check student_profile payments if present
        if hasattr(self, 'student_profile') and self.student_profile:
            try:
                for p in self.student_profile.payments.all():
                    has_entry = any(
                        item.get('receipt_number') == p.receipt_number or 
                        (item.get('transaction_id') == p.transaction_ref and item.get('status') == p.status)
                        for item in history
                    )
                    if not has_entry:
                        p_proof = None
                        if p.payment_proof:
                            try:
                                raw_p_url = p.payment_proof.url
                                p_proof = request.build_absolute_uri(raw_p_url) if request else raw_p_url
                            except Exception:
                                p_proof = str(p.payment_proof)
                        history.append({
                            'event': 'payment_approved' if p.status == 'verified' else ('payment_rejected' if p.status == 'rejected' else 'payment_approval_pending'),
                            'payment_choice': p.payment_mode,
                            'amount': float(p.amount),
                            'transaction_id': p.transaction_ref,
                            'receipt_number': p.receipt_number,
                            'status': p.status,
                            'date': p.payment_date.isoformat() if p.payment_date else None,
                            'created_at': p.created_at.isoformat() if p.created_at else None,
                            'payment_screenshot': p_proof,
                            'payment_proof': p_proof,
                            'note': p.note or None,
                        })
            except Exception:
                pass

        # If payment was submitted/received but missing from history, synthesize it
        has_payment_entry = any(item.get('event') in ('payment_received', 'payment_submitted', 'payment_verified', 'payment_approved', 'payment_approval_pending') for item in history)
        if not has_payment_entry and (self.razorpay_payment_id or self.payment_submitted_at or self.transaction_id or self.payment_screenshot):
            history.append({
                'event': 'payment_received' if self.razorpay_payment_id else 'payment_submitted',
                'payment_choice': self.payment_choice or ('online' if self.razorpay_payment_id else 'offline'),
                'amount': float(self.payment_amount or 0),
                'transaction_id': self.transaction_id or self.razorpay_payment_id,
                'razorpay_payment_id': self.razorpay_payment_id,
                'payment_screenshot': proof_url,
                'payment_proof': proof_url,
                'payment_note': self.payment_note or None,
                'status': 'paid' if (self.is_razorpay_paid or self.status in ('enrolled', 'approved')) else 'approval_pending',
                'paid_at': self.payment_submitted_at.isoformat() if self.payment_submitted_at else (self.updated_at.isoformat() if self.updated_at else None),
                'date': self.payment_submitted_at.date().isoformat() if self.payment_submitted_at else (self.updated_at.date().isoformat() if self.updated_at else None),
            })

        token_amt = float(getattr(self.fee_structure, 'token_amount', 0) or 0) if self.fee_structure else 0.0
        total_fee = float(self.total_fees or 0)
        rem_fee = float(self.remaining_fees or 0)
        p_type = self.payment_type or 'full_payment'
        p_type_display = self.get_payment_type_display() if hasattr(self, 'get_payment_type_display') else p_type.replace('_', ' ').title()

        # Enrich every history object with complete fee details, proof, and dates
        for item in history:
            item.setdefault('payment_type', p_type)
            item.setdefault('payment_type_display', p_type_display)
            item.setdefault('total_fees', total_fee)
            item.setdefault('token_amount', token_amt)
            item.setdefault('remaining_fees', rem_fee)
            item.setdefault('terms_note', self.token_payment_terms_note)
            item.setdefault('fee_terms_note', self.token_payment_terms_note)

            # Dates
            item_date = item.get('date') or (item.get('timestamp')[:10] if item.get('timestamp') else None) or (item.get('created_at')[:10] if item.get('created_at') else None) or (item.get('paid_at')[:10] if item.get('paid_at') else None)
            if not item_date and self.submitted_at:
                item_date = self.submitted_at.date().isoformat()
            item['date'] = item_date
            if not item.get('created_at') and item.get('timestamp'):
                item['created_at'] = item['timestamp']
            elif not item.get('created_at') and self.submitted_at:
                item['created_at'] = self.submitted_at.isoformat()

            # Proof / screenshots for offline or submitted payments
            choice = item.get('payment_choice') or self.payment_choice
            item['payment_choice'] = choice
            item['payment_choice_display'] = 'Cheque' if choice in ('cheque', 'check') else dict(PAYMENT_CHOICE_CHOICES).get(choice, str(choice).title() if choice else 'N/A')

            if proof_url and (choice in ('cash', 'cheque', 'check', 'offline') or item.get('event') in ('payment_submitted', 'offline_payment_selected') or not item.get('payment_screenshot')):
                item.setdefault('payment_screenshot', proof_url)
                item.setdefault('payment_proof', proof_url)
            else:
                item.setdefault('payment_screenshot', None)
                item.setdefault('payment_proof', None)

        return history


class AdmissionStatusHistory(models.Model):
    """Tracks every status change on an Admission."""
    admission  = models.ForeignKey(Admission, on_delete=models.CASCADE, related_name='status_history')
    status     = models.CharField(max_length=20, choices=ADMISSION_STATUS_CHOICES)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
    )
    note       = models.TextField(blank=True)
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'admission_status_history'
        ordering = ['changed_at']

    def __str__(self):
        changed_by = self.changed_by.get_username() if self.changed_by else 'System'
        return f"{self.admission} → {self.status} by {changed_by}"