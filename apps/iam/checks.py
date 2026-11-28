"""A system check: in production, somebody must be a platform admin."""

from typing import Any

from django.conf import settings
from django.core.checks import CheckMessage, Tags, Warning, register
from django.db import DatabaseError

from .models import PlatformAdmin


@register(Tags.database)
def platform_admin_exists(
    app_configs: Any = None, databases: Any = None, **kwargs: Any
) -> list[CheckMessage]:
    """Warn when nobody is a platform admin outside dev mode.

    Nobody means: no oid in IAM_PLATFORM_ADMIN_OIDS and no PlatformAdmin row.
    """
    if settings.AUTH_MODE == "dev" or settings.IAM_PLATFORM_ADMIN_OIDS:
        return []
    try:
        if PlatformAdmin.objects.exists():
            return []
    except DatabaseError:  # the tables do not exist yet (before the first migrate)
        return []
    return [
        Warning(
            "Nobody is a platform admin.",
            hint="Set IAM_PLATFORM_ADMIN_OIDS or run: manage.py platform_admin grant --oid <uuid>",
            id="iam.W001",
        )
    ]
