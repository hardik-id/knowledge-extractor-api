from django.urls import path

from apps.extraction.api import views

urlpatterns = [
    path("runs/<str:run_id>/stages/extract/definition", views.definition),
    path(
        "runs/<str:run_id>/stages/extract/definition/versions",
        views.definition_versions,
    ),
    path(
        "runs/<str:run_id>/stages/extract/definition/versions/<int:version>",
        views.definition_version,
    ),
    path(
        "runs/<str:run_id>/stages/extract/definition/versions/<int:version>/restore",
        views.restore_definition_version,
    ),
    path("runs/<str:run_id>/stages/<str:stage>/executions", views.executions),
    path("runs/<str:run_id>/files/<str:file_id>/extraction", views.extraction),
    path("runs/<str:run_id>/files/<str:file_id>/extraction/records", views.records),
    path(
        "runs/<str:run_id>/files/<str:file_id>/extraction/records/<str:record_id>",
        views.record,
    ),
    path(
        "runs/<str:run_id>/files/<str:file_id>/extraction/records/<str:record_id>"
        "/fields/<str:field_id>",
        views.field,
    ),
    path(
        "runs/<str:run_id>/files/<str:file_id>/extraction/records/<str:record_id>"
        "/values/<str:value_id>",
        views.value,
    ),
]
