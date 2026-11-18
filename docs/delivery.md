# Delivery: how the backlog gets built

The backlog is GitHub issues. A PBI is one issue and one pull request, and its number is the issue number: PBI-007 is #7. The tracking issue for the foundation epic is #25.

Agents build the PBIs through the workflows in `.claude/workflows/`. Each workflow delivers a few PBIs that belong together.

## What happens to one PBI

```
implement ──► review ───────────┐
          └─► test and validate ┴─► merge
                     │                ▲
                     └─► fix ─────────┘   (only when blocked, two rounds at most)
```

| Stage | Who | What |
| --- | --- | --- |
| Implement | Sonnet, effort by tier | Reads the issue, works in its own git worktree, uses the generators, runs the checks, opens the pull request |
| Review | Sonnet; Opus for the `complex` tier | Has not seen the work. Judges the pull request against the issue: correctness, security, conventions, generators, tests, simplicity. Major findings block, minor ones don't |
| Test and validate | Sonnet | Takes a clean checkout of the pull request. Runs every check, then does each "Done when" item against the running app and real PostgreSQL. Reports evidence, changes nothing |
| Fix | Sonnet, then Opus for a second round | Only the points that block. After two rounds the PBI is marked blocked and the PBIs that wait for it are skipped |
| Merge | Sonnet | One at a time: rebase onto `main`, checks again, squash-merge, file each minor finding as an issue (`review-followup`, `priority: low`), clean up |

Review and validation run side by side. A workflow ends with a full check of `main`.

A PBI starts as soon as the PBIs it depends on are merged, so a workflow has no idle waves.

## The workflows

| Workflow | PBIs (`→` in order, `∥` side by side) | Start it after |
| --- | --- | --- |
| `foundation-1-bootstrap` | #1 → #2 → #3 → #4 | nothing: it is first, alone |
| `foundation-2-quality` | #5 → (#6 ∥ #7) | 1 |
| `foundation-3-enablement` | #8 ∥ #9 | 1 |
| `foundation-4-core` | #10 → (#11 ∥ #12) | 2 |
| `foundation-5-platform` | (#13 → #14) ∥ #15 | 2 |
| `foundation-6-auth` | #16 → ((#17 → #18) ∥ #19) | 4 and 5 |
| `foundation-7-api-docs` | #20 → #21 | 6 |
| `foundation-8-agent-kit` | #22 → #23 | 7 and 3 |

Workflows 2 and 3 can run at the same time, and so can 4 and 5. A workflow refuses to start while a PBI it depends on is still open.

#24 (sign-in against a real Entra tenant) is done with the repository owner, not by a workflow.

## Running one

In Claude Code, ask for the workflow by name ("run the workflow foundation-2-quality") from a session started in this repository, or give the path of its file.

Options, passed as the workflow's arguments:

| Option | Effect |
| --- | --- |
| `dryRun: true` | Print the plan. No agent starts |
| `only: [6, 7]` | Deliver just these PBIs of the workflow |
| `merge: false` | Stop at "ready": reviewed and validated, not merged |
| `force: true` | Start although a PBI outside the run is still open |
| `repoDir: "/path"` | The main checkout, when the session starts somewhere else |

Running a workflow again is safe. A closed issue is skipped, and an open pull request is picked up at review and validation.

## What every agent works with

| For PBI-012 | Value |
| --- | --- |
| Worktree | `.worktrees/pbi-012` (validation uses `.worktrees/pbi-012-check`) |
| Branch | `pbi/012-v1-health` |
| Database | `ke_pbi_012` (validation: `ke_pbi_012_check`) |
| Port | 8112 (validation: 8212) |

Two things are shared, so agents leave them alone:

- **The PostgreSQL server** from `compose.yaml`. One server for every worktree; each agent has its own database on it. Nobody stops or resets it.
- **Git hooks.** They live in the main checkout and apply to every worktree. Agents run `uv run pre-commit run --all-files` by hand and never install hooks from a worktree.

The main checkout stays on `main` and clean. A workflow won't start otherwise.

## Changing the workflows

The files in `.claude/workflows/` are generated. A workflow script can't import anything, so each one carries a copy of the engine.

```sh
# edit tools/delivery/plan.json (which PBIs, order, tiers, models)
# or   tools/delivery/engine.js (the stages and what agents are told)
python3 tools/delivery/build.py
node tools/delivery/test_engine.mjs    # runs the workflows with fake agents
```

A new epic is a new set of entries in `plan.json`: its PBIs under `items`, and one entry under `workflows` for each group that is delivered together.
