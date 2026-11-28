from typing import cast

from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view
from rest_framework.pagination import BasePagination
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.pagination import DefaultPagination
from apps.iam import tenants
from apps.iam.routes import SIGNED_IN, requires
from apps.identity.models import User

from .audit_serializers import AuditEntrySerializer, AuditList, AuditQuerySerializer


@requires(
    GET=SIGNED_IN
)  # a platform admin, or an admin of the tenant: checked by the read
@extend_schema(parameters=[AuditQuerySerializer], responses=AuditList)
@api_view(["GET"])
def audit_list(request: Request) -> Response:
    """Role changes, newest first. A platform admin sees all; a tenant admin their tenant's."""
    query = AuditQuerySerializer(data=request.query_params)
    query.is_valid(raise_exception=True)
    entries = tenants.list_audit(
        cast(User, request.user), query.validated_data.get("tenant_id")
    )
    paginator: BasePagination = DefaultPagination()
    page = paginator.paginate_queryset(entries, request)
    return paginator.get_paginated_response(AuditEntrySerializer(page, many=True).data)
