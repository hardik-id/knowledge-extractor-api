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
| `/tenants/{tenant_id}/members` | GET | `tenant.members.list` |
| `/tenants/{tenant_id}/members` | POST | `tenant.members.manage` |
| `/tenants/{tenant_id}/members/{user_id}` | PUT, DELETE | `tenant.members.manage` |
| `/users` | GET | signed in (a platform admin lists and searches everyone; a tenant admin asks for one exact `?preferred_username=`; anyone else 403; checked by the view) |
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
- Adding a non-member by id (`set_tenant_role`) is for a platform admin or an operator only: ids are small numbers, so a tenant admin could count through them. For a tenant admin a non-member is `user_not_found`, as for an id nobody has. A tenant admin adds through `add_tenant_member` with the exact sign-in name (case does not matter; no match, or two people with the name, is `user_not_found`; a member already is 409 `already_a_member`). `change_member_role` is for a member only.
- `remove_tenant_member` also removes the person's `WorkspaceMembership` rows in the tenant's workspaces, in the same transaction, with one `workspace.member.remove` entry each. A workspace may be left without an owner; an admin gives it one.
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

## Tenant members and finding people

`GET /tenants/{id}/members` (`?search=` on name or sign-in name, paged) answers `{ "items": [{ "user": { "id", "name", "preferred_username" }, "role", "added_at" }], "next" }` to any member, admin or platform admin of the tenant. `POST` adds a person by `{ "preferred_username", "role" }`; a platform admin may give `{ "user_id", "role" }` instead (a tenant admin who does gets 403). `PUT /tenants/{id}/members/{user_id}` with `{ "role" }` changes a role and `DELETE` removes the person. For PUT and DELETE every id that is not a member (a person of another tenant, an id nobody has, text) answers the same 404 `user_not_found`, so ids cannot be walked.

`GET /users`: a platform admin gets everyone who has signed in (`?search=`, paged), or, with `?preferred_username=<exact>`, only that one person (the exact name wins over `?search=`). A tenant admin gets only `?preferred_username=<exact>`: that one person, or an empty list when nobody or more than one person has the name; a part of a name finds nothing. Anyone else gets 403. A person who is deactivated is not found.
