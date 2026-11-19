from django.contrib import admin

from .models import DefinitionVersion, Extraction


@admin.register(DefinitionVersion)
class DefinitionVersionAdmin(admin.ModelAdmin):  # type: ignore[type-arg]  # generic only for stubs
    list_display = ("run", "version", "created_at")


@admin.register(Extraction)
class ExtractionAdmin(admin.ModelAdmin):  # type: ignore[type-arg]  # generic only for stubs
    list_display = ("file", "revision", "definition_version", "created_at")
