"""Routes for a tenant's members and for finding people (``/tenants/{id}/members``, ``/users``)."""

from typing import Any

from django.urls import path

from .members_views import member, members
from .users_views import users

urlpatterns: list[Any] = [
    path("tenants/<str:tenant_id>/members", members),
    path("tenants/<str:tenant_id>/members/<str:user_id>", member),
    path("users", users),
]
