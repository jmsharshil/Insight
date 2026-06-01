from django.contrib import admin
from .models import Batch


@admin.register(Batch)
class BatchAdmin(admin.ModelAdmin):
    list_display = ('name', 'branch', 'course', 'is_active')
    list_filter = ('is_active', 'branch')
    search_fields = ('name',)
