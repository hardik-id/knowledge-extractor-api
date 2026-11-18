# API conventions

Every endpoint follows these rules. The UI relies on them.

- **Paths.** Under `/api/v1`, lowercase, no trailing slash: `/api/v1/runs`, not `/api/v1/runs/`.
- **JSON.** Field names are `snake_case`.
- **Ids.** A UUID, time-ordered (version 7), written in its canonical lowercase form. Every model extends `BaseModel` (`apps/core/models.py`), which provides it.
- **Timestamps.** ISO 8601 in UTC, for example `2026-11-18T09:30:00Z`. `BaseModel` provides `created_at` and `updated_at`.
- **Errors.** `{ "code", "message" }`, see `errors.md`.

## Lists and paging

A list answers an object, never a bare array:

```json
{ "items": [ { "id": "..." } ], "next": "cD0wMThm..." }
```

- Newest first.
- `next` is an opaque cursor, or `null` on the last page. Ask for the next page with `?cursor=<next>`; do not build or parse cursors.
- `?page_size=` sets the page size. The default is 20 and the maximum is 100; a larger value is capped, not rejected.
- Following `next` until it is `null` visits every row once, even while rows are added.

The default is `DefaultPagination` (`apps/core/pagination.py`), set as `DEFAULT_PAGINATION_CLASS`; a list view gets it by using DRF's generic list views.
