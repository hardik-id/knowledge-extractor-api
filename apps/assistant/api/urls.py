from django.urls import path

from apps.assistant.api import views

urlpatterns = [
    path("runs/<str:run_id>/extraction/assistant/messages", views.messages),
]
