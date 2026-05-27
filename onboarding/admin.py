from django.contrib import admin
from .models import Admission,AdmissionStatusHistory
# Register your models here.

admin.site.register(Admission)
admin.site.register(AdmissionStatusHistory)