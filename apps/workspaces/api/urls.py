from django.urls import path

from apps.workspaces.api import views

urlpatterns = [
    path("workspaces", views.workspaces),
    path("workspaces/<str:workspace_id>", views.workspace_detail),
    path("workspaces/<str:workspace_id>/members", views.workspace_members_list),
    path("workspaces/<str:workspace_id>/members/<str:user_id>", views.workspace_member),
    # The old paths, answered by the same code until the UI has moved (#493 removes them).
    path("projects", views.projects),
    path("projects/<str:project_id>", views.project_detail),
]
