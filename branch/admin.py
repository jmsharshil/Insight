from django.contrib import admin
from branch.models import *

@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ('id', 'organization', 'name', 'address', 'city', 'state', 'pincode', 'phone', 'email', 'principal_name',)
    search_fields = ('name', 'email', 'phone',)
    list_filter = ('organization', 'is_deleted', 'updated_at', 'created_at', 'is_active',)
