from django.contrib import admin
from .models import SupportQuery, SupportQueryMessage

class SupportQueryMessageInline(admin.TabularInline):
    model = SupportQueryMessage
    extra = 0
    readonly_fields = ('sender', 'message', 'attachment', 'is_resolution', 'created_at')

@admin.register(SupportQuery)
class SupportQueryAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'organization', 'assigned_to', 'title', 'description', 'attachment', 'status', 'created_at')
    list_filter = ('status', 'organization', 'created_at')
    search_fields = ('title', 'description', 'user__email')
    readonly_fields = ('id', 'user', 'organization', 'created_at')
    inlines = [SupportQueryMessageInline]

@admin.register(SupportQueryMessage)
class SupportQueryMessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'query', 'sender', 'is_resolution', 'created_at')
    list_filter = ('is_resolution', 'created_at')
    search_fields = ('message', 'query__title', 'sender__email')