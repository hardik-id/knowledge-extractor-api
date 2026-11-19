from django.urls import path

from apps.extraction.api import views

urlpatterns = [
    path("runs/<str:run_id>/stages/extract/definition", views.definition),
    path("runs/<str:run_id>/files/<str:file_id>/extraction", views.extraction),
]
