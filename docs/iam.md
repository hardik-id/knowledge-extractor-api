# IAM: tenants, workspaces and roles

Who may do what. The code is `apps/iam`; the table is `apps/iam/roles.py` and one test pins it. Epic: #483. Nothing is enforced by this app yet: later PBIs enforce it on the routes. Visibility and 404 versus 403 are in `docs/permissions.md`; sign-in is in `docs/auth.md`.

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

## Workspace membership

`WorkspaceMembership` (workspace, person, role; one row per pair) is what makes a workspace visible: `Workspace.objects.visible_to(user)` is the workspaces the person has a row in. A workspace belongs to a tenant (`Workspace.tenant`). Creating one needs `workspaces.create` in the tenant, and the creator gets the `owner` row in the same transaction, recorded as `workspace.role.set`. `apps.iam.selectors.workspace_role(user, workspace_id)` and `workspace_permissions(user, workspace_id)` read it. See `docs/workspaces.md`.
