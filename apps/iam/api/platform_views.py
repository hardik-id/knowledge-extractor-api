from typing import Any, cast

from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from apps.iam import tenants
from apps.iam.roles import Permission
from apps.iam.routes import requires
from apps.identity.models import User

from .platform_serializers import PlatformAdminList, PlatformAdminSerializer


def _wire(user: Any, source: str) -> dict[str, Any]:
    return {
        "user_id": user.pk,
        "name": user.name or user.preferred_username,
        "source": source,
    }


@requires(GET=Permission.TENANTS_MANAGE)
@extend_schema(responses=PlatformAdminList)
@api_view(["GET"])
def platform_admins(request: Request) -> Response:
    """The platform admins who have signed in. ``source`` is ``setting`` for those the setting names."""
    items = [_wire(u, source) for u, source in tenants.list_platform_admins()]
    return Response(
        {"items": PlatformAdminSerializer(items, many=True).data, "next": None}
    )


@requires(PUT=Permission.TENANTS_MANAGE, DELETE=Permission.TENANTS_MANAGE)
@extend_schema(methods=["PUT"], request=None, responses=PlatformAdminSerializer)
@extend_schema(methods=["DELETE"], responses={204: None})
@api_view(["PUT", "DELETE"])
def platform_admin_detail(request: Request, user_id: int) -> Response:
    """Make a person who has signed in a platform admin (PUT), or take it away (DELETE)."""
    actor = cast(User, request.user)
    if request.method == "DELETE":
        tenants.remove_platform_admin(actor, user_id)
        return Response(status=204)
    tenants.add_platform_admin(actor, user_id)
    return Response(
        PlatformAdminSerializer(_wire(*tenants.platform_admin_item(user_id))).data
    )
