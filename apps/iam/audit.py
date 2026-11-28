"""The one writer of the audit record. See docs/iam.md, rule 7.

Every service that grants, changes or removes a role calls ``record`` inside the
transaction that makes the change, so a change and its entry are saved together
and a refused change leaves no entry.
"""

from typing import Any
from uuid import UUID

import structlog

from .models import AuditEntry, Tenant

log = structlog.get_logger(__name__)


def record(
    *,
    actor: Any | None,
    action: str,
    target_user: Any | None = None,
    tenant: Tenant | None = None,
    workspace_id: UUID | None = None,
    old_role: str = "",
    new_role: str = "",
) -> AuditEntry:
    """Insert one entry and log ``iam.changed`` with ids and roles only, never names.

    ``actor`` is None for a command or a migration. The ``oid`` and ``tid`` of both
    people are copied into the entry, so it still says who they were after a
    person's row is deleted.
    """
    entry = AuditEntry.objects.create(
        actor=actor,
        action=action,
        target_user=target_user,
        tenant=tenant,
        workspace_id=workspace_id,
        actor_oid=getattr(actor, "oid", None),
        actor_tid=getattr(actor, "tid", None),
        target_oid=getattr(target_user, "oid", None),
        target_tid=getattr(target_user, "tid", None),
        old_role=old_role,
        new_role=new_role,
    )
    log.info(
        "iam.changed",
        action=action,
        actor_id=getattr(actor, "pk", None),
        target_user_id=getattr(target_user, "pk", None),
        tenant_id=str(tenant.pk) if tenant else None,
        workspace_id=str(workspace_id) if workspace_id else None,
        old_role=old_role,
        new_role=new_role,
    )
    return entry
