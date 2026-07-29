from django.contrib import admin
from .models import SupportQuery
@admin.register(SupportQuery)
class SupportQueryAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'organization', 'title', 'description', 'attachment', 'created_at')
    list_filter = ('organization', 'created_at')
    search_fields = ('title', 'description')
    readonly_fields = ('id', 'user', 'organization', 'created_at')