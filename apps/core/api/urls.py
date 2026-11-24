from django.urls import path

from apps.core.api import health, status

urlpatterns = [
    path("health", health.health),
    path("ready", health.ready),
    path("status", status.backend_status),
]
