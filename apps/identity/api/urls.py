from django.urls import path

from apps.identity.api import views

urlpatterns = [
    path("me", views.me),
]
