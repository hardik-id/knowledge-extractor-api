# Delivery: how the backlog gets built

The backlog is GitHub issues. A PBI is one issue and one pull request, and its number is the issue number: PBI-007 is #7, PBI-142 is #142. Tracking issues: #25 for the foundation epic, #157 for the Studio epic.

Agents build the PBIs through the workflows in `.claude/workflows/`. Each workflow delivers a few PBIs that belong together. The same workflows deliver work in the UI repository (`hardik-id/knowledge-extractor`), where the items are that repository's issues.

## What happens to one PBI

```
implement ──► review ───────────┐
          └─► test and validate ┴─► merge
                     │                ▲
                     └─► fix ─────────┘   (only when blocked, two rounds at most)
```

| Stage | What |
| --- | --- |
| Implement | Reads the issue, works in its own git worktree, uses the generators, runs the checks, opens the pull request |
| Review | Has not seen the work. Judges the pull request against the issue: correctness, security, conventions, generators, tests, simplicity. Major findings block, minor ones don't |
| Test and validate | Takes a clean checkout of the pull request. Runs every check, then does each "Done when" item against the running app. UI work that needs the API also runs the end-to-end suite (`npm run test:e2e`) against the running stack, on its own `E2E_PORT`. Reports evidence, changes nothing |
| Fix | Only the points that block. After two rounds the PBI is marked blocked and the PBIs that wait for it are skipped |
| Merge | One at a time: rebase onto `main`, checks again, squash-merge, file each minor finding as a low-priority issue, clean up |

Review and validation run side by side. A workflow ends with a full check of `main`.

The end-to-end suite is the merge gate, because there is no CI:

- **UI work that needs the API:** each PBI's validation runs `npm run test:e2e` against the stack that is already running (the engine never restarts it), and the final check of `main` runs it once more. A failing test blocks like any other failed check.
- **API work:** per-PBI validation stays as it is, because the stack runs `main`, not a worktree. The final check of `main` rebuilds the stack from `main` (`make up`) and runs `make e2e`. A failure is reported as a problem of that check, with the names of the failing tests.
- **Docs and delivery tooling:** an item whose label is `documentation`, or whose title names docs or the delivery workflows, engine or tooling, skips the suite. The rule is the `DOCS_OR_TOOLING` line in `tools/delivery/engine.js`.
- **Ports:** every agent that starts a UI app uses a free port of its own and never 3000 (a person's dev server) or 3100 (the runner's default). Each PBI gets `E2E_PORT` 5100 plus its number (validation: 7100 plus), the final check 6000 plus the workflow's index.

A PBI starts as soon as the PBIs it depends on are merged, so a workflow has no idle waves.

## Who does what

The model follows the PBI's tier (the `tier:` label).

| Tier | Implement | Review | Second fix round |
| --- | --- | --- | --- |
| `simple`, `normal` | Sonnet | Sonnet | Opus |
| `complex` | Sonnet, more effort | Opus | Opus |
| `hard` | Opus | Opus | Fable |

Sonnet tests and validates, and merges. Haiku does the preparation step.

## The Studio epic

| Workflow | PBIs (`→` in order, `∥` side by side) | Start it after |
| --- | --- | --- |
| `studio-1-ground` | #135 ∥ #136 | nothing |
| `studio-ui-1-apps` | UI #38 | nothing |
| `studio-2-platform` | #137 ∥ #138 ∥ (#139 → #153) | 1 |
| `studio-3-data` | #140 → (#141 ∥ (#142 → #143)) | 1 |
| `studio-4-live` | #144 ∥ #145 ∥ (#148 → #151) | 2 and 3 |
| `studio-5-assistant` | #146 → #147 | 4 |
| `studio-6-extraction` | #149 → #150 → #152 | 4 |
| `studio-7-stack` | #154 ∥ #155 ∥ #156 | 5 and 6 |
| `studio-ui-2-backend` | UI #39 → UI #40 | 7, with the stack running (`make up`) |

Workflows on the same line of "start it after" can run at the same time: 1 with ui-1, 2 with 3, 5 with 6. A workflow refuses to start while a PBI it depends on is still open.

## The projects epic

Tracked in #327. Named projects, documents that can change, visible configuration versions.

| Workflow | PBIs (`→` in order, `∥` side by side) | Start it after |
| --- | --- | --- |
| `projects-1-api` | (#322 → #323) ∥ #324 ∥ #325 | nothing |
| `projects-2-api-flow` | #326 | 1 |
| `projects-ui-1-services` | UI #52 | 2, with the stack rebuilt and running |
| `projects-ui-2-routes` | UI #53 | ui-1 |
| `projects-ui-3-screens` | UI #54 ∥ #55 ∥ #56 ∥ #57 | ui-2 |
| `projects-ui-4-walk` | UI #58 | ui-3 |

## The assistant epic

Tracked in #272. The assistant's LLM agent becomes a package with tools that help a subject-matter expert see what can be extracted.

| Workflow | PBIs (`→` in order, `∥` side by side) | Start it after |
| --- | --- | --- |
| `assistant-1-structure` | #263 → #264 → #265 | nothing |
| `assistant-2-tools` | (#266 → #267) ∥ #268 ∥ #269 ∥ #270 | 1 |
| `assistant-3-guidance` | #271 | 2 |

## The end-to-end tests epic

Tracked in #357. Playwright journeys in the UI repository, run with one command, so a change to the UI or the API is checked in a real browser without a person clicking through it.

| Workflow | PBIs (`→` in order, `∥` side by side) | Start it after |
| --- | --- | --- |
| `e2e-1-runner` | UI #96 | nothing, with the stack running (`make up`) |
| `e2e-2-journeys` | UI #97 ∥ #98 ∥ #99 | 1, with the stack running |
| `e2e-3-command` | #356 | 1. Can run beside 2 |
| `e2e-4-stability` | UI #123 | 2 and 3, with the stack running |
| `e2e-5-engine` | #363 | 3. Can run beside 4 |
| `e2e-6-checks` | UI #124 ∥ #125 ∥ #126 | 4, with the stack running |

## The definition models epic

Tracked in #372. One description of the extraction definition's shape: nested pydantic models.

| Workflow | PBIs (`→` in order, `∥` side by side) | Start it after |
| --- | --- | --- |
| `definition-1-models` | #369 → #370 → #371 | nothing |

## The templates epic

Tracked in #392. Several starting configurations for extraction (ADR, Skill, Policy rule, blank) instead of one hard-wired default.

| Workflow | PBIs (`→` in order, `∥` side by side) | Start it after |
| --- | --- | --- |
| `templates-1-api` | #389 → (#390 ∥ #391) | nothing |
| `templates-ui-1-services` | UI #159 | 1, with the stack rebuilt and running |
| `templates-ui-2-screens` | UI #160 ∥ #161 | ui-1, and `define-2-table-width` |

## The modern look epic

UI milestone "Modern look". "Polder for apps": lines instead of frames, small radii, an app type scale and density, neutral ground, a slim shell.

| Workflow | PBIs (`→` in order, `∥` side by side) | Start it after |
| --- | --- | --- |
| `look-1-fixes` | UI #176 | nothing |
| `look-2-foundation` | UI #177 → #178 | 1 |
| `look-3-screens` | UI #179 ∥ #180 ∥ #181 | 2 |

## The deploy epic

Tracked in #409. A Helm chart for the dev environment of a Kubernetes cluster. Templates only: checked by rendering, not on a cluster.

| Workflow | PBIs (`→` in order, `∥` side by side) | Start it after |
| --- | --- | --- |
| `deploy-1-chart` | #406 → (#407 ∥ #408) | nothing |
| `deploy-ui-1-image` | UI #182 | nothing |

## Single items

| Workflow | PBIs | Start it after |
| --- | --- | --- |
| `define-1-field-table` | UI #148 | nothing, with the stack running (`make up`) |
| `session-1-refused-token` | UI #149 | nothing, with the stack running. Can run beside `define-1-field-table` |
| `define-2-table-width` | UI #158 | `define-1-field-table`, with the stack running |

The foundation epic was delivered the same way by `foundation-1-bootstrap` to `foundation-8-agent-kit` (#1 to #23).

## Running one

In Claude Code, ask for the workflow by name from a session started in this repository, or give the path of its file.

Options, passed as the workflow's arguments:

| Option | Effect |
| --- | --- |
| `dryRun: true` | Print the plan. No agent starts |
| `only: [146]` | Deliver just these PBIs of the workflow |
| `merge: false` | Stop at "ready": reviewed and validated, not merged |
| `force: true` | Start although a PBI outside the run is still open |
| `repoDir: "/path"` | The main checkout, when the session starts somewhere else |
| `uiDir: "/path"` | API workflows: the UI checkout, which agents read as the contract |
| `apiDir`, `apiUrl` | UI workflows: the backend checkout, and where the running backend answers |

Running a workflow again is safe. A closed issue is skipped, and an open pull request is picked up at review and validation.

## What every agent works with

| For PBI-142 | Value |
| --- | --- |
| Worktree | `.worktrees/pbi-142` (validation uses `.worktrees/pbi-142-check`) |
| Branch | `pbi/142-runs` (in the UI repository: `studio/039-studio-http`) |
| Database | `ke_pbi_142` (validation: `ke_pbi_142_check`) |
| Port | 8242 (validation: 9242). UI work: 3139 and 4139; its end-to-end runner (`E2E_PORT`): 5139 and 7139 |

Some things are shared, so agents leave them alone:

- **The infrastructure in `compose.yaml`**: `db`, `redis`, `otel-collector`. One set for every worktree; each agent has its own database. Nobody stops or resets them. Agents run the app from their worktree, not through the compose `api` and `worker`.
- **Git hooks.** They live in the main checkout and apply to every worktree. Agents run `uv run pre-commit run --all-files` by hand and never install hooks from a worktree.
- **For UI work, the running backend** and port 3000, which may be a person's own dev server.

The main checkout stays on `main` and clean. A workflow won't start otherwise.

## Changing the workflows

The files in `.claude/workflows/` are generated. A workflow script can't import anything, so each one carries a copy of the engine.

```sh
# edit tools/delivery/plan.json (which PBIs, order, tiers, models)
# or   tools/delivery/engine.js (the stages and what agents are told)
python3 tools/delivery/build.py
node tools/delivery/test_engine.mjs    # runs the workflows with fake agents
```

A new epic is a new set of entries in `plan.json`: its PBIs under `items`, and one entry under `workflows` for each group that is delivered together. An entry with `"kind": "ui"` is work in the UI repository.
