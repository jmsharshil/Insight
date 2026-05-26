from django.contrib import admin

# Register your models here.
from .models import Lead,LeadStage

admin.site.register(Lead)
admin.site.register(LeadStage)