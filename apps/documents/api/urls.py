from django.urls import path

from apps.documents.api import views

urlpatterns = [
    path("documents", views.document_list),
    path("documents/<path:document_id>", views.document_read),
]
