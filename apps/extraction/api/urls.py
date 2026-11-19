from django.urls import path

from apps.extraction.api import views

urlpatterns = [
    path("runs/<str:run_id>/stages/extract/definition", views.definition),
]
