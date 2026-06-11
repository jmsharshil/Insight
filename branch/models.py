from django.db import models
from auth_user.models import Organization
from django.utils import timezone

# Create your models here.
import uuid

class Branch(models.Model):
    id = models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    organization = models.ForeignKey(Organization,on_delete=models.CASCADE,related_name='branches',null=True,blank=True)
    name = models.CharField(max_length=200, blank=True)
    address = models.TextField()
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    pincode = models.CharField(max_length=10)
    phone = models.CharField(max_length=20)
    email = models.EmailField()
    principal_name = models.CharField(max_length=150,blank=True)
    logo = models.ImageField(upload_to="branches/logos/",null=True,blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    allowed_radius_meters = models.PositiveIntegerField(default=100)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False)
    
    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.name:
            year = timezone.now().year
            prefix = f"BRN-{year}-"
            last = Branch.objects.filter(name__startswith=prefix).order_by('-name').first()
            if last and last.name:
                try:
                    seq = int(last.name.split('-')[-1]) + 1
                except (ValueError, IndexError):
                    seq = 1
            else:
                seq = 1
            self.name = f"{prefix}{seq:04d}"
        super().save(*args, **kwargs)