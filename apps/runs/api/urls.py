from django.urls import path

from apps.runs.api import views

urlpatterns = [
    path("runs", views.run_create),
    path("runs/<str:run_id>", views.run_detail),
    path("runs/<str:run_id>/documents", views.run_documents),
]
