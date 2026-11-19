from django.contrib import admin

from .models import DefinitionVersion


@admin.register(DefinitionVersion)
class DefinitionVersionAdmin(admin.ModelAdmin):  # type: ignore[type-arg]  # generic only for stubs
    list_display = ("run", "version", "created_at")
