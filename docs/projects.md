# Projects

A project is a name on a run: one run with its documents, extraction configuration, conversation with the assistant and records. A person starts one project per use case, comes back to it later, and keeps several side by side. Nothing inside a project is duplicated under `/projects`: documents, configuration, records and conversation keep going through the run's own endpoints, with the project's `run_id`.

A project is private to its owner. Someone else's project and an unknown id answer 404 `project_not_found`.

## Endpoints

| Method and path | Does |
| --- | --- |
| `POST /api/v1/projects` | `{ name, description? }` answers 201 with the project and makes its empty run in the same transaction |
| `GET /api/v1/projects` | `{ items, next }`, default pagination, last activity first |
| `GET /api/v1/projects/{id}` | one project |
| `PATCH /api/v1/projects/{id}` | `name` and/or `description` |
| `DELETE /api/v1/projects/{id}` | deletes the project, its run and everything on it, and closes the run's sockets (4404) |

`name` is required, at most 120 characters, and not blank; otherwise 422 `validation_error`. `description` is optional text. `template_id` is optional: the id of a template from `GET /api/v1/definition-templates`. The project's configuration is then version 1, made from that template with the note `From template: <name>`; without it the default template (ADR) is used. An unknown id is 422 `unknown_template` and no project is made. There is no call to apply a template to an existing project: load one into the editor and save it with `PUT …/definition`.

## On the wire

```json
{
  "id": "...",
  "name": "Architecture decisions",
  "description": "",
  "run_id": "...",
  "document_count": 3,
  "configuration_version": 2,
  "created_at": "...",
  "updated_at": "..."
}
```

- `document_count` is the number of files in the run.
- `configuration_version` is the latest saved version of the run's extraction definition. A new project starts at 1, made from its template.
- `updated_at` is the last activity: the newest change among the project, the run's files and cells, its definition versions, its records (and their values) and its assistant messages. It is worked out in the list query itself, with subqueries, so the list makes the same number of queries however many projects there are. No other app writes to the project when something changes. Removing a file or a message does not count as activity, because nothing is left to read a time from.
- The list is ordered by `updated_at` (newest first), then by id.

## The run of a project

`DELETE /api/v1/runs/{run_id}` on a run that a project owns answers 409 `run_belongs_to_project`. Delete the project instead. The UI should add a line for the two new codes, `project_not_found` and `run_belongs_to_project`.
