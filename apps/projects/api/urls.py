from django.urls import path

from apps.projects.api import views

urlpatterns = [
    path("projects", views.projects),
    path("projects/<str:project_id>", views.project_detail),
]
