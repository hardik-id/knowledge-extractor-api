# Permissions

The rule: what a person may do follows their role, on every route. What they may not see does not exist (404); what they see but may not do is refused (403 `forbidden`). Authentication is in `docs/auth.md`; the roles and the permission table are in `docs/iam.md`, with the table of every route.

## A route says what it needs

Every view under `/api/v1` carries `@requires` (`apps/iam/routes.py`) above `@api_view`, one keyword per HTTP method it answers:

```python
@requires(GET=Permission.WORKSPACE_VIEW, PUT=Permission.WORKSPACE_EDIT)
@extend_schema(...)
@api_view(["GET", "PUT"])
def definition(request, run_id): ...
```

A value is a `Permission` of `apps/iam/roles.py`, `SIGNED_IN` or `OPEN`. A method left out, or one declared that the view does not answer, stops the app at start. Who checks what:

- `OPEN`: nobody; no sign-in (`health`, `ready`).
- `SIGNED_IN`: a signed-in person. The service may check more: `POST /workspaces` checks `workspaces.create` in the tenant.
- An application permission (`status.test`, `tenants.manage`, `users.list`, held by platform admins only): checked by the declaration, before the view runs. Anybody else is 403 `forbidden`.
- A workspace permission (`workspace.view`, `.edit`, `.run`, `.manage`): checked by the function that fetches the workspace or the run, which is given the permission. The declaration only needs a signed-in person, so that a hidden row is 404 before a refused one is 403.

## A run or a workspace is fetched with the permission

Request code gets a run or a workspace only through a function that takes the permission, with no default:

```python
run = runs.get_run(user, run_id, Permission.WORKSPACE_EDIT)
file = runs.get_run_file(user, run_id, file_id, Permission.WORKSPACE_VIEW)
workspace = workspaces.get_workspace(user, workspace_id, Permission.WORKSPACE_MANAGE)
```

- 404 (`run_not_found`, `workspace_not_found`): the person has no role in the workspace. An unknown id, a malformed id and somebody else's workspace give the identical answer, so nobody can probe for ids.
- 403 `forbidden`: the person has a role in it that does not give the permission.

The permission comes from the person's role in the workspace (`apps.iam.selectors.workspace_permissions`). A run with no workspace (`POST /runs`) is seen only by the person who made it, and they may do everything on it.

Admins get no content from their admin role: a tenant admin or a platform admin who has no role in a workspace gets 404 on it, like anybody else (`docs/iam.md`, rule 1).

A service checks the permission of what it does (`save_definition` needs `workspace.edit`, `start_execution` `workspace.run`); the view's declaration says the same, and the sweep (below) fails when they disagree. Code that already holds the run (inside a service, a job, the assistant) passes the run object on (`extraction.selectors.definition_of(run)`) and does not fetch it again.

## Jobs and the assistant act for the run

A background job and the assistant's reply are for the run, not for a person. They read the run they were given (`runs.get_any_run`, or the run object of the message or cell), never through somebody's workspace role. The run's documents are read with `extraction.selectors.input_text(run_file)`: the file is already in the run, and the catalog is asked with the document rights of the person who made the run. `get_any_run` is for operator commands and jobs only, never for a request.

## `owner`

`owner` on a row says who made it. It decides nothing about access, with one exception: a run with no workspace is visible to the person who made it. `OwnedModel` (`apps/core/models.py`) gives `owner` and a manager with `visible_to(user)`; a model visible to more than its maker overrides `visible_to` on its queryset (`Workspace`: through `WorkspaceMembership`; `Run`: through its workspace).

## One row

`get_visible_or_404(Model, user, pk, code="...")` (`apps/core/permissions.py`) returns the row if `Model.objects.visible_to(user)` has it, otherwise raises `ApiError(code)`. `get_run` and `get_workspace` start with it. Register the resource's own code in `apps/core/errors.py` first.

## The sweep

`apps/iam/tests/test_route_sweep.py` walks the URL configuration. It fails with the route's name when a route or a method declares nothing. Then it calls every route and method on a real workspace as a stranger, a tenant admin and a platform admin who are not members, a viewer, an editor and the owner, and checks the answers against the declaration and the permission table: an anonymous call 401, a non-member 404, a viewer 403 on everything but `workspace.view`, an editor 403 only on `workspace.manage`, the owner nothing refused; an application permission is 403 for all but a platform admin. Ids come from the fixtures; a body that gets a request past its own validation is in `BODIES`. A route it cannot call goes in `NOT_CALLED` with the reason (empty today). It checks the live-update socket too: it needs `workspace.view`.

## Tests

`apps.core.tests` has `SharedNote` (visible to all when shared) and views built only from `get_visible_or_404`; see `apps/core/tests/test_permissions.py`. For roles, use the factories: `UserFactory()` is a member of Default, `TenantMembershipFactory()` a person in that tenant only, `WorkspaceFactory()` a workspace whose `owner` has the owner role (`owner_role="none"`: nobody has a role in it); add a `WorkspaceMembership` for a viewer or an editor.
