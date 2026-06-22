import uuid
from django.db import models
from django.conf import settings
from django.utils import timezone

from branch.models import Branch
from students.models import StudentProfile
from faculty.models import FacultyProfile

class ItemCategory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='inventory_categories')
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'inventory_item_categories'
        ordering = ['name']
        unique_together = ('branch', 'name')

    def __str__(self):
        return f"{self.name} ({self.branch.name})"


class Item(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    category = models.ForeignKey(ItemCategory, on_delete=models.CASCADE, related_name='items')
    name = models.CharField(max_length=200)
    sku = models.CharField(max_length=50, unique=True, help_text="Stock Keeping Unit / Unique Item Code")
    description = models.TextField(blank=True)
    size = models.CharField(max_length=50, blank=True, help_text="e.g., S, M, L, XL (useful for uniforms)")
    
    total_stock = models.IntegerField(default=0, help_text="Current available quantity")
    reorder_level = models.IntegerField(default=10, help_text="Stock level at which a reorder is triggered")
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'inventory_items'
        ordering = ['name']

    def __str__(self):
        return f"{self.name} (SKU: {self.sku})"


class StockTransaction(models.Model):
    TRANSACTION_TYPES = [
        ('purchase', 'Purchase/Inward'),
        ('allocation', 'Allocation/Issued'),
        ('return', 'Returned by Student/Faculty'),
        ('damage', 'Damaged/Lost'),
        ('adjustment', 'Manual Adjustment')
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name='transactions')
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    quantity = models.IntegerField(help_text="Positive for inward (purchase, return), negative for outward (allocation, damage)")
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, help_text="Cost at the time of transaction")
    
    reference = models.CharField(max_length=100, blank=True, help_text="Invoice number or Allocation ID reference")
    notes = models.TextField(blank=True)
    
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='inventory_transactions')
    transaction_date = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'inventory_stock_transactions'
        ordering = ['-transaction_date']

    def __str__(self):
        return f"{self.item.name} | {self.get_transaction_type_display()} | Qty: {self.quantity}"

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new:
            # Automatically update the item's total stock
            self.item.total_stock += self.quantity
            self.item.save(update_fields=['total_stock'])


class ItemAllocation(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending Approval'),
        ('issued', 'Issued'),
        ('returned', 'Returned'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name='allocations')
    
    # Can be assigned to either a student or a faculty
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, null=True, blank=True, related_name='inventory_allocations')
    faculty = models.ForeignKey(FacultyProfile, on_delete=models.CASCADE, null=True, blank=True, related_name='inventory_allocations')
    
    quantity = models.PositiveIntegerField(default=1)
    size = models.CharField(max_length=20, blank=True, help_text="Specific size allocated (e.g., M, L, XL)")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='issued')
    
    issued_at = models.DateTimeField(default=timezone.now)
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='items_issued')
    
    returned_at = models.DateTimeField(null=True, blank=True)
    return_notes = models.TextField(blank=True)

    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'inventory_item_allocations'
        ordering = ['-issued_at']

    def __str__(self):
        assignee = self.student.admission_number if self.student else (self.faculty.user.name if self.faculty else 'Unknown')
        return f"Allocated {self.item.name} to {assignee}"
