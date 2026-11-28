"""Everything under /api/v1/. Mount a new app here, one line per app."""

from django.urls import include, path

urlpatterns = [
    path("", include("apps.core.api.urls")),
    path("", include("apps.identity.api.urls")),
    path("", include("apps.documents.api.urls")),
    path("", include("apps.runs.api.urls")),
    path("", include("apps.realtime.api.urls")),
    path("", include("apps.extraction.api.urls")),
    path("", include("apps.assistant.api.urls")),
    path("", include("apps.workspaces.api.urls")),
    path("", include("apps.iam.api.urls")),
]
