from django.urls import path

from apps.documents.api import views

urlpatterns = [
    path("documents", views.document_list),
]
