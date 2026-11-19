from django.urls import path

from apps.realtime.api import views

urlpatterns = [
    path("ws-ticket", views.ws_ticket),
]
