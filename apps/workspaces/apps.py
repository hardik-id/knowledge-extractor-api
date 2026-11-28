from django.apps import AppConfig


class WorkspacesConfig(AppConfig):
    name = "apps.workspaces"
    label = "projects"  # the app's old name: kept so the migration history holds
