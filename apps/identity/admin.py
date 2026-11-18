from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class IdentityUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ('Entra ID', {'fields': ('oid', 'tid', 'name', 'preferred_username')}),
    )
    list_display = ('username', 'name', 'preferred_username', 'oid', 'tid', 'is_staff')
