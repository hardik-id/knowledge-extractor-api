from django.urls import path

from apps.extraction.api import views

urlpatterns = [
    path("runs/<str:run_id>/stages/extract/definition", views.definition),
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
