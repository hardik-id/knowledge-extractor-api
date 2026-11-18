---
name: add-setting
description: Add a configuration variable (environment-driven setting) to this API. Use when code needs a value that differs per machine or environment, such as a URL, a flag or a limit.
---

# Add a setting

Settings come from the environment through `config/settings`. Never read `os.environ` in app code.

## Steps

1. In `config/settings/base.py` read it with the `env` object in the matching labelled section: `env.str`, `env.bool`, `env.int`, `env.list`. Give a default that is safe in every environment, or none when production must set it.
2. If only one environment differs, override in `local.py`, `test.py` or `production.py`.
3. Add the variable with a one-line comment to `.env.example` in the same change. Commented out when it has no useful default.
4. Use it with `from django.conf import settings`.
5. If it matters to operators, add it to the table in the relevant `docs/*.md` (for example `docs/auth.md`, `docs/docker.md`).
6. A test with `pytest`'s `settings` fixture, then `make check`.

## Done when

The variable is in `base.py` and `.env.example`, and `make check` passes.

## Pitfalls

- A secret has no default and never goes into git or `.env.example` with a real value.
- `.env` is ignored by git; do not commit it.
- `schema` and tests run with fixed settings (`config.settings.test`), so a new variable must work without your `.env`.
