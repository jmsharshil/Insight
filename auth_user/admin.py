from django.contrib import admin
from auth_user.models import *

@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'logo_url', 'footer_text', 'primary_color', 'website_url', 'created_at',)
    search_fields = ('name',)
    list_filter = ('created_at',)

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('password', 'last_login', 'is_superuser', 'id', 'organization', 'username', 'email', 'phone', 'name', 'role',)
    search_fields = ('name', 'email', 'phone',)
    list_filter = ('last_login', 'organization', 'branch', 'linked_student', 'is_staff', 'role', 'is_superuser', 'created_at',)

@admin.register(EmailOTP)
class EmailOTPAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'otp', 'created_at', 'is_verified',)
    list_filter = ('is_verified', 'created_at', 'user',)

@admin.register(PasswordSetToken)
class PasswordSetTokenAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'token', 'created_at', 'is_used',)
    list_filter = ('is_used', 'created_at', 'user',)
