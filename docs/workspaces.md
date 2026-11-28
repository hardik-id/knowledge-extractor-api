# Workspaces

A workspace is a name on a run: one run with its documents, extraction configuration, conversation with the assistant and records. A person starts one workspace per use case, comes back to it later, and keeps several side by side. Nothing inside a workspace is duplicated under `/workspaces`: documents, configuration, records and conversation keep going through the run's own endpoints, with the workspace's `run_id`.

A workspace lives in one tenant and is seen through membership: a person sees it when they have a role in it (`owner`, `editor` or `viewer`, `docs/iam.md`). `owner` on the row is who made it and no longer decides access. A workspace the person has no role in and an unknown id answer 404 `workspace_not_found`. What each role may do on each route is in `docs/iam.md` (reading needs `workspace.view`, renaming and deleting `workspace.manage`).

## Endpoints

| Method and path | Does |
| --- | --- |
| `POST /api/v1/workspaces` | `{ name, description?, template_id?, tenant_id? }` answers 201 with the workspace, makes its empty run and gives the creator the `owner` role, in one transaction |
| `GET /api/v1/workspaces` | `{ items, next }`, default pagination, last activity first; `?tenant_id=` keeps one tenant's (malformed id: 422) |
| `GET /api/v1/workspaces/{id}` | one workspace |
| `PATCH /api/v1/workspaces/{id}` | `name` and/or `description` |
| `DELETE /api/v1/workspaces/{id}` | deletes the workspace, its run and everything on it, and closes the run's sockets (4404) |
| `GET /api/v1/workspaces/{id}/members` | `{ items }`: who has a role, owners first, then by name |
| `PUT /api/v1/workspaces/{id}/members/{user_id}` | `{ role }` (`owner`, `editor` or `viewer`): adds the person or changes their role; answers the member |
| `DELETE /api/v1/workspaces/{id}/members/{user_id}` | takes the person out; 204 |

## Members

A member on the wire is `{ "user": { "id", "name", "preferred_username" }, "role", "added_at" }`. Anyone with a role in the workspace reads the list, and so does an admin of its tenant or a platform admin who is not a member. Changing it needs `workspace.members.manage`: an owner, an admin of the tenant or a platform admin; the admins still get 404 on the workspace's content until they add themselves. Only a person in the workspace's tenant can be given a role (422 `not_a_tenant_member`, also for an unknown id), and a workspace keeps one owner (409 `last_owner`). A removed member gets 404 on the workspace at the next request. The rules and the audit entries are in `docs/iam.md`. There is no `/projects` alias for these routes.

`tenant_id` is the tenant the workspace goes to. Without it the person's only tenant is used; a person in several tenants must say which (422 `validation_error`), a person in none cannot create one (403 `forbidden`). A tenant the person is not in is 404 `tenant_not_found`. Creating needs `workspaces.create` in that tenant.

`name` is required, at most 120 characters, and not blank; otherwise 422 `validation_error`. `description` is optional text. `template_id` is optional: the id of a template from `GET /api/v1/definition-templates`. The workspace's configuration is then version 1, made from that template with the note `From template: <name>`; without it the default template (ADR) is used. An unknown id is 422 `unknown_template` and no workspace is made. There is no call to apply a template to an existing workspace: load one into the editor and save it with `PUT …/definition`.

## On the wire

```json
{
  "id": "...",
  "name": "Architecture decisions",
  "description": "",
  "run_id": "...",
  "tenant_id": "...",
  "role": "owner",
  "permissions": ["workspace.edit", "workspace.manage", "..."],
  "document_count": 3,
  "configuration_version": 2,
  "created_at": "...",
  "updated_at": "..."
}
```

- `tenant_id` is the tenant the workspace is in. `role` is the person's role in it and `permissions` their permission names in it, sorted (`apps.iam.selectors.workspace_role` and `workspace_permissions` say the same to other code).
- `document_count` is the number of files in the run.
- `configuration_version` is the latest saved version of the run's extraction definition. A new workspace starts at 1, made from its template.
- `updated_at` is the last activity: the newest change among the workspace, the run's files and cells, its definition versions, its records (and their values) and its assistant messages. It is worked out in the list query itself, with subqueries, so the list makes the same number of queries however many workspaces there are. No other app writes to the workspace when something changes. Removing a file or a message does not count as activity, because nothing is left to read a time from.
- The list is ordered by `updated_at` (newest first), then by id.

## The run of a workspace

`DELETE /api/v1/runs/{run_id}` on a run that a workspace owns answers 409 `run_belongs_to_workspace`. Delete the workspace instead. The UI should add a line for the two new codes, `workspace_not_found` and `run_belongs_to_workspace`.

## The old paths

`/api/v1/projects` and `/api/v1/projects/{project_id}` still answer through the same code and are marked deprecated in the schema, until the UI has moved. They are removed in #493. The app label stays `projects` (the migration history), the table is `workspaces_workspace`.

## Existing data

The migrations put every existing workspace in the tenant "Default" and make its owner `owner` of it.

## Runs

A run is visible to a person when its workspace is (`Run.objects.visible_to`), or when it has no workspace and they own it. Every run route goes through `runs.get_run`, so they follow.
