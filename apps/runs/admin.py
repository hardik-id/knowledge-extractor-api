from django.contrib import admin

from .models import Cell, Run, RunFile


@admin.register(Run)
class RunAdmin(admin.ModelAdmin):  # type: ignore[type-arg]  # generic only for stubs
    list_display = ("id", "owner", "created_at")


@admin.register(RunFile)
class RunFileAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("name", "run", "source", "etag")


@admin.register(Cell)
class CellAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("file", "stage", "status", "updated_at")
