import uuid
from django.db import models
from django.conf import settings
from django.utils import timezone


REIMBURSEMENT_STATUS_CHOICES = [
    ('pending', 'Pending'),
    ('approved', 'Approved'),
    ('rejected', 'Rejected'),
]


class Reimbursement(models.Model):
    """
    Staff expense reimbursement claim.
    Applicable to all staff roles. Approved amounts are credited to the user's monthly pay.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='reimbursements',
        help_text="Staff member applying for the expense reimbursement"
    )
    branch = models.ForeignKey(
        'branch.Branch',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reimbursements',
        help_text="Branch associated with this expense claim"
    )
    title = models.CharField(max_length=255, help_text="Short title of the expense")
    description = models.TextField(blank=True, help_text="Detailed description of the expense")
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Refund amount claimed"
    )
    proof = models.FileField(
        upload_to='reimbursements/proofs/',
        help_text="Receipt, bill, or supporting document"
    )
    expense_date = models.DateField(
        default=timezone.now,
        help_text="Date when the expense occurred"
    )
    status = models.CharField(
        max_length=20,
        choices=REIMBURSEMENT_STATUS_CHOICES,
        default='pending'
    )

    # Approver details
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_reimbursements'
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    # Rejection details
    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='rejected_reimbursements'
    )
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    # Monthly Payroll Integration
    payroll_run = models.ForeignKey(
        'payroll.PayrollRun',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reimbursements',
        help_text="Payroll run in which this reimbursement was included"
    )
    payslip = models.ForeignKey(
        'payroll.PaySlip',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reimbursements',
        help_text="Payslip in which this reimbursement was credited"
    )
    is_paid = models.BooleanField(
        default=False,
        help_text="True when the corresponding payslip/payroll run has been disbursed"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'reimbursements'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} - ₹{self.amount} ({self.user.name or self.user.email}) [{self.status}]"
