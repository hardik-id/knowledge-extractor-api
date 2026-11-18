---
name: add-error-code
description: Register a new API error code (such as run_not_found) and raise it. Use when an endpoint needs an error the UI can tell apart from the generic ones.
---

# Add an error code

Every error body is `{ "code", "message" }`. A code must be registered, or `ApiError` raises `ValueError`. See `docs/errors.md`.

## Steps

1. Add one line to `ERRORS` in `apps/core/errors.py`: `"run_not_found": ErrorCode(404, "Run not found."),`. snake_case, the status that fits.
2. Add the row to the table in `docs/errors.md`.
3. Raise it: `raise ApiError("run_not_found")`, or pass it as `code=` to `get_visible_or_404`.
4. Test it through the API: the status and `response.json()["code"]`.
5. Say in the pull request whether the UI needs words for it: the UI keeps its own message per code, so a new code needs a line there (the UI's `docs/*.md` and `contracts.ts`).
6. `make check`.

## Done when

The code is in `ERRORS` and `docs/errors.md`, a test shows the response, and `make check` passes.

## Pitfalls

- Reuse a generic code (`not_found`, `conflict`, `validation_error`) when the UI does not need to tell the cases apart; do not add a code per message.
- A 403 for a row the person may not see leaks that it exists: use 404.
- Never put internals in `message` or `details`.
