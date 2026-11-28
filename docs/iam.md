# IAM: tenants, workspaces and roles

Who may do what. The code is `apps/iam`; the table is `apps/iam/roles.py` and one test pins it. Epic: #483. Roles are granted by `services.py` and enforced on every route (the table below). How a route says what it needs and how it is checked: `docs/permissions.md`; sign-in is in `docs/auth.md`.

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

## The routes

What each route needs, declared with `@requires` on its view (`apps/iam/routes.py`); the sweep `apps/iam/tests/test_route_sweep.py` fails when a route declares nothing or answers otherwise. Paths are under `/api/v1`. The deprecated `/projects` paths (until #493) need the same as `/workspaces`.

| Route | Method | Needs |
| --- | --- | --- |
| `/health`, `/ready` | GET | open |
| `/me` | GET | signed in |
| `/status` | GET | signed in |
| `/status/test` | POST | `status.test` |
| `/documents`, `/documents/{document_id}` | GET | signed in |
| `/definition-templates` | GET | signed in |
| `/ws-ticket` | POST | signed in |
| `/workspaces` | GET, POST | signed in (POST: `workspaces.create` in the tenant, checked by the service) |
| `/workspaces/{workspace_id}` | GET | `workspace.view` |
| `/workspaces/{workspace_id}` | PATCH, DELETE | `workspace.manage` |
| `/runs` | POST | signed in (a run of one's own, with no workspace; needs `workspaces.create` in some tenant, checked by the view) |
| `/runs/{run_id}` | GET | `workspace.view` |
| `/runs/{run_id}` | DELETE | `workspace.manage` (a workspace's run is 409 `run_belongs_to_workspace`) |
| `/runs/{run_id}/documents` | PUT | `workspace.edit` |
| `/runs/{run_id}/stages/extract/definition` | GET | `workspace.view` |
| `/runs/{run_id}/stages/extract/definition` | PUT | `workspace.edit` |
| `/runs/{run_id}/stages/extract/definition/versions`, `.../versions/{version}` | GET | `workspace.view` |
| `/runs/{run_id}/stages/extract/definition/versions/{version}/restore` | POST | `workspace.edit` |
| `/runs/{run_id}/stages/extract/chunking/generate` | POST | `workspace.run` |
| `/runs/{run_id}/stages/{stage}/executions` | POST | `workspace.run` |
| `/runs/{run_id}/files/{file_id}/extraction` | GET | `workspace.view` |
| `/runs/{run_id}/files/{file_id}/extraction/records` | POST | `workspace.edit` |
| `.../records/{record_id}` | PATCH, DELETE | `workspace.edit` |
| `.../records/{record_id}/fields/{field_id}` | PUT | `workspace.edit` |
| `.../records/{record_id}/values/{value_id}` | PATCH | `workspace.edit` |
| `/runs/{run_id}/extraction/assistant/messages` | GET | `workspace.view` |
| `/runs/{run_id}/extraction/assistant/messages` | POST, DELETE | `workspace.edit` |
| `/tenants` | GET | signed in (a platform admin gets every tenant with counts, anyone else their own) |
| `/tenants` | POST | `tenants.manage` |
| `/tenants/{tenant_id}` | PATCH, DELETE | `tenants.manage` |
| `/tenants/{tenant_id}/workspaces` | GET | `tenant.workspaces.list` |
| `/platform-admins`, `/platform-admins/{user_id}` | GET, PUT, DELETE | `tenants.manage` |
| `/audit` | GET | signed in; with `?tenant_id=`, `tenant.members.manage` in that tenant; without, a platform admin (all) or a tenant admin (their tenants) |
| socket `ws/runs/{run_id}/` | connect | `workspace.view` (otherwise closed with 4404) |

A workspace permission is checked against the person's role in the workspace of the route's run or workspace: no role is 404, a role without the permission 403 `forbidden`. A tenant admin or a platform admin with no role in the workspace gets 404 too (rule 1).

A tenant permission is checked by `apps.iam.selectors.get_tenant(user, tenant_id, permission)`, the one way a request fetches a tenant: a tenant the person has no role in is 404 `tenant_not_found` (a platform admin sees every tenant), a tenant seen without the permission is 403. `tenant_permissions(user, tenant_id)` is what the person holds there, from their role and from being a platform admin.

The sweep's rule for a route that needs one permission: a person whose roles hold it is answered, a person who sees the tenant or the workspace without it gets 403, anyone else 404. It calls each route as eight people (`ROLES` in the sweep): one in another tenant, one in no tenant, a member of the tenant with no role in the workspace, a tenant admin and a platform admin who are not members of the workspace, a viewer, an editor and the owner. A route whose rule is not one permission (a list that answers differently per person) says what each of them gets in `EXPECTED`. A new route adds its body to `BODIES` and nothing else.

The iam routes are in `apps/iam/api`: `members_urls.py` (a tenant's members, finding people) and `tenants_urls.py` (tenants, a tenant's workspaces, platform admins, the audit list), joined in `urls.py`. Workspace members are routes of a workspace and live in `apps/workspaces/api`.

## Other apps

Point at the models by string (`"iam.Tenant"`); call `apps.iam.selectors` (`is_platform_admin`, `tenant_role`, `tenant_permissions`, `get_tenant`, `tenant_of_workspace`, `tenants_of`, `default_tenant`, `workspace_role`, `workspace_permissions`), never the models. A new column an older running container may write without needs `db_default` as well as `default`.

## Granting roles (`apps/iam/services.py`)

`set_tenant_role`, `remove_tenant_member`, `grant_platform_admin` and `revoke_platform_admin` take the acting person first (None is an operator: no permission check, no actor in the entry). Each runs in one transaction with its audit entry, so a refused change leaves none, and a change that changes nothing (the same role, already an admin) records nothing.

- Tenant changes need `tenant.members.manage`: a tenant the actor may not see is 404 `tenant_not_found`, one they see but may not change is 403 `forbidden`. Platform admin changes need a platform admin (403 otherwise).
- 409 `last_platform_admin`: the last platform admin (a row, or a signed-in person whose `oid` is listed) cannot be revoked. 409 `last_tenant_admin`: a tenant admin cannot leave or step down when no other admin stays, unless a platform admin (or an operator) acts.
- A person who never signed in is 404 `user_not_found`; so is removing someone who is not a member.
- Races: tenant changes lock the tenant row, platform admin changes take one advisory lock, before the rule counts anything.
- Audit actions: `tenant.role.set` (also the first sign-in, with no actor), `tenant.member.remove`, `platform_admin.grant`, `platform_admin.revoke`.

## Platform admins

A person is a platform admin when their `oid` is in `IAM_PLATFORM_ADMIN_OIDS` (no row, changed only in the setting) or a `PlatformAdmin` row exists. On a developer machine in dev mode (`config.settings.local`, `AUTH_MODE=dev`) the dev issuer's default person is listed when the setting is not set at all, so a local stack has a platform admin with no setup; production never gets this, because it refuses dev mode. In production a system check (`iam.W001`, run by `manage.py check --database default` and `migrate`) warns when there is neither. Operators use:

```sh
uv run python manage.py platform_admin list
uv run python manage.py platform_admin grant --oid <uuid>    # the person must have signed in once
uv run python manage.py platform_admin revoke --oid <uuid>
```

## First sign-in

When `apps.identity` creates a user it calls `services.join_default_tenant` in the same transaction: the person becomes `IAM_DEFAULT_TENANT_ROLE` (default `member`; empty means none) of the default tenant, and the entry is recorded. Only creation does this.

## Workspace membership

`WorkspaceMembership` (workspace, person, role; one row per pair) is what makes a workspace visible: `Workspace.objects.visible_to(user)` is the workspaces the person has a row in. A workspace belongs to a tenant (`Workspace.tenant`). Creating one needs `workspaces.create` in the tenant, and the creator gets the `owner` row in the same transaction, recorded as `workspace.role.set`. `apps.iam.selectors.workspace_role(user, workspace_id)` and `workspace_permissions(user, workspace_id)` read it. See `docs/workspaces.md`.

## Tenants, platform admins and the audit list

The services and reads are in `apps/iam/tenants.py`; the views in `apps/iam/api/tenants_views.py`, `platform_views.py` and `audit_views.py`.

- **Tenants.** `GET /tenants` is `{ items, next }` (not paged: `next` is null), by name. A platform admin gets every tenant with `member_count` and `workspace_count`; anyone else gets the tenants they belong to with both counts null. `role` is the person's role in it (null for a platform admin who is not a member). `POST /tenants` and `PATCH /tenants/{id}` take `{ "name" }` (409 `tenant_name_taken`, ignoring case; a tenant keeps the right to change the case of its own name). `DELETE` is 409 `default_tenant` for Default and 409 `tenant_not_empty` while it has workspaces. A new tenant has no admin: a platform admin names one with the members routes. Audit actions: `tenant.create`, `tenant.rename`, `tenant.delete`. An entry of a deleted tenant keeps its place but has no tenant any more, so only the unfiltered list of a platform admin shows it.
- **A tenant's workspaces.** `GET /tenants/{id}/workspaces`, paged, last activity first: `id`, `name`, `owners` (`id`, `name`), `member_count`, `no_owner`, `last_activity`, `created_at`. Never the description, configuration, documents, records or conversation.
- **Platform admins.** `GET /platform-admins` lists the active people who have signed in and are admins, with `source`: `row`, or `setting` for a person listed in `IAM_PLATFORM_ADMIN_OIDS`. `PUT /platform-admins/{user_id}` grants (the person must have signed in: 404 `user_not_found`), `DELETE` revokes through `services.revoke_platform_admin` (409 `last_platform_admin`), and 409 `platform_admin_by_setting` for a person the setting names: change the setting instead.
- **The audit list.** `GET /audit?tenant_id=`, paged, newest first. With a tenant: whoever holds `tenant.members.manage` there (404 `tenant_not_found` if unseen, 403 if seen without it). Without: a platform admin gets everything, a tenant admin the entries of the tenants they administer, anyone else 403. An item has only `id`, `action`, `actor` and `target` (`{ id, name }`, or null once the person's row is gone), `tenant_id`, `workspace_id`, `old_role`, `new_role`, `created_at`: never an `oid`, `tid` or sign-in name. The entry itself keeps `actor_oid` and `target_oid` for the record.
