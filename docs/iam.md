# IAM: tenants, workspaces and roles

Who may do what. The code is `apps/iam`; the table is `apps/iam/roles.py` and one test pins it. Epic: #483. Roles are granted by `services.py`; nothing is enforced on the routes yet (later PBIs). Visibility and 404 versus 403 are in `docs/permissions.md`; sign-in is in `docs/auth.md`.

## The levels

| Level | Roles | Who assigns them |
| --- | --- | --- |
| Application | Platform admin (`PlatformAdmin` row) | the setting `IAM_PLATFORM_ADMIN_OIDS`, or another platform admin |
| Tenant | `admin`, `member` (`TenantMembership`) | a platform admin, or an admin of that tenant |
| Workspace | `owner`, `editor`, `viewer` | an owner of that workspace, or an admin of its tenant |

A tenant is a team or a customer inside the application. It is not the Entra directory (the token's `tid`). Roles are fixed, defined in code, assigned in the app and stored here; Entra only proves who the person is.

## The permissions

| Permission | Platform admin | Tenant admin | Tenant member | Owner | Editor | Viewer |
| --- | --- | --- | --- | --- | --- | --- |
| `tenants.manage` | yes | | | | | |
| `users.list` | yes | | | | | |
| `status.test` | yes | | | | | |
| `tenant.members.manage` | yes | yes | | | | |
| `tenant.workspaces.list` | yes | yes | | | | |
| `tenant.members.list` | yes | yes | yes | | | |
| `workspaces.create` | | yes | yes | | | |
| `workspace.members.manage` | yes | yes | | yes | | |
| `workspace.manage` | | | | yes | | |
| `workspace.run` | | | | yes | yes | |
| `workspace.edit` | | | | yes | yes | |
| `workspace.view` | | | | yes | yes | yes |

## The rules

1. Content needs a workspace role. An admin manages access but does not read content.
2. 404 before 403: a workspace the person has no role in does not exist for them; one they can see but not change answers 403 `forbidden`.
3. A new person becomes `IAM_DEFAULT_TENANT_ROLE` (default `member`) of the default tenant.
4. Nobody locks the door behind them: the last platform admin cannot be removed, a workspace keeps one owner, a tenant keeps one admin unless a platform admin makes the change.
5. Only people who have signed in once can be given a role; a person is `oid` + `tid`, never an email address.
6. Removing access works at once, also for an open live-update socket.
7. Every change of a role is recorded (`AuditEntry`: who, whose, what, when). Entries are only inserted and survive the deletion of a person or a tenant: each keeps the `oid` and `tid` of the actor and of the person it is about. `apps.iam.audit.record` is the one writer; a service calls it inside the transaction that makes the change, and it also logs `iam.changed` with ids and roles, never names.
8. The migration `0002_default_tenant` creates the tenant "Default" (`is_default`; at most one) and makes every existing person a `member` of it. It reverses by deleting that tenant.

## Other apps

Point at the models by string (`"iam.Tenant"`); call `apps.iam.selectors` (`is_platform_admin`, `tenant_role`, `tenants_of`, `default_tenant`), never the models. A new column an older running container may write without needs `db_default` as well as `default`.

## Granting roles (`apps/iam/services.py`)

`set_tenant_role`, `remove_tenant_member`, `grant_platform_admin` and `revoke_platform_admin` take the acting person first (None is an operator: no permission check, no actor in the entry). Each runs in one transaction with its audit entry, so a refused change leaves none, and a change that changes nothing (the same role, already an admin) records nothing.

- Tenant changes need `tenant.members.manage`: a tenant the actor may not see is 404 `tenant_not_found`, one they see but may not change is 403 `forbidden`. Platform admin changes need a platform admin (403 otherwise).
- 409 `last_platform_admin`: the last platform admin (a row, or a signed-in person whose `oid` is listed) cannot be revoked. 409 `last_tenant_admin`: a tenant admin cannot leave or step down when no other admin stays, unless a platform admin (or an operator) acts.
- A person who never signed in is 404 `user_not_found`; so is removing someone who is not a member.
- Races: tenant changes lock the tenant row, platform admin changes take one advisory lock, before the rule counts anything.
- Audit actions: `tenant.role.set` (also the first sign-in, with no actor), `tenant.member.remove`, `platform_admin.grant`, `platform_admin.revoke`.

## Platform admins

A person is a platform admin when their `oid` is in `IAM_PLATFORM_ADMIN_OIDS` (no row, changed only in the setting) or a `PlatformAdmin` row exists. In production a system check (`iam.W001`, run by `manage.py check --database default` and `migrate`) warns when there is neither. Operators use:

```sh
uv run python manage.py platform_admin list
uv run python manage.py platform_admin grant --oid <uuid>    # the person must have signed in once
uv run python manage.py platform_admin revoke --oid <uuid>
```

## First sign-in

When `apps.identity` creates a user it calls `services.join_default_tenant` in the same transaction: the person becomes `IAM_DEFAULT_TENANT_ROLE` (default `member`; empty means none) of the default tenant, and the entry is recorded. Only creation does this.
