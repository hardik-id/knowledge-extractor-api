from django.urls import path

from apps.core.api import health

urlpatterns = [
    path("health", health.health),
    path("ready", health.ready),
]
