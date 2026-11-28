from django.urls import path

from apps.workspaces.api import views

urlpatterns = [
    path("workspaces", views.workspaces),
    path("workspaces/<str:workspace_id>", views.workspace_detail),
    # The old paths, answered by the same code until the UI has moved (#493 removes them).
    path("projects", views.projects),
    path("projects/<str:project_id>", views.project_detail),
]
