# Permissions

The rule: you only see what you may see, and what you may not see does not exist. Authentication is in `docs/auth.md`; this is what happens after it.

## The convention

Every selector takes the acting user and returns only the rows that user may see. A view never filters by owner itself and never fetches by bare id.

## Owned things

A model that belongs to one person extends `OwnedModel` (`apps/core/models.py`): an `owner` and a manager with `visible_to(user)`.

```python
class Run(OwnedModel): ...


def list_runs(user):
    return Run.objects.visible_to(user)
```

A model visible to more than its owner overrides `visible_to` on its own queryset (subclass `OwnedQuerySet`) and `can_be_changed_by(user)` on the model.

## One row

`get_visible_or_404(Run, user, pk, code="run_not_found")` (`apps/core/permissions.py`) returns the row or raises `ApiError(code)`. A missing id, a malformed id and somebody else's row give the identical answer, so nobody can probe for ids. Register the resource's own code in `apps/core/errors.py` first.

## Changing

404 and 403 mean different things:

- 404: the person may not see the row. It does not exist for them.
- 403 `forbidden`: the person may see the row but may not change it. Fetch with `get_visible_or_404`, then call `require_can_change(row, user)`.

```python
run = get_visible_or_404(Run, request.user, pk, code="run_not_found")
require_can_change(run, request.user)
```

## Tests

The test-only app `apps.core.tests` has `SharedNote` (visible to all when shared, changeable by its owner) and views built only from the helpers; see `apps/core/tests/test_permissions.py`.
