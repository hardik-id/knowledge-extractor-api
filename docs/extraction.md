# Extraction

What turns a document into records is replaceable, and running it again never undoes a person's work. The pieces are in `apps/extraction`.

## The extractor interface

`extractors/base.py`. An extractor takes the text of a document, a `Definition` (a definition version as plain data: `version`, `prompt`, `record_types`) and the example records (accepted records marked `use_as_example`), and returns raw records: a `RawRecord` has its record type id, its span and, per field, `RawValue`s with the quotes they came from. A field that was not found is one value that is `None` with no spans. Nothing in the interface touches the database or the network.

Spans are `{start, end, quote}` and offsets count code points (Python `str` indexing, `end` exclusive).

## Choosing one

`EXTRACTOR` selects the implementation through `get_extractor()`: `scripted`, or the dotted path of a class (how tests swap in a fake). Any other value stops the app at start. An extractor that calls a model, or a bridge to the existing extraction service, comes later behind the same interface.

## The scripted extractor

`extractors/scripted.py`, a port of the UI's `src/services/mock/mock-extractor.ts`; no model, the same answer every time.

- A record is a `## ` heading that starts with the record type's name (case does not matter), down to the next `## ` heading.
- A field comes from the heading (a `title` field: the text after `ADR-012: `), from a `**Label:** value` line or from a `### Label` section (down to the next heading). The label matches the field's name or key, ignoring case, `_`, `-` and runs of spaces; a `decided_on` field also matches `Date`.
- A `multiple` field on a `**Label:**` line gives one value per comma-separated item.
- A `quote` field carries the exact text and its span. An `inferred` field carries the evidence span and a tidied value: the first matching choice for a `choice` field, an ISO date for a `date` field (`3 November 2026`, `November 3, 2026`, `2026-11-03`).

The port was checked against the TypeScript: both give the same records for the sample documents, for hand-made edge cases and for 300 generated documents.

## From raw to stored records

`extractors/records.py`, `stored_records(text, raw_records)`. For one file it checks every span against the text, anchors a quote whose offsets do not fit (`spans.resolve_span`), keeps a quote that is not in the text with `anchored: false`, and marks every record and value `llm` and `suggested`. A record whose own span cannot be placed is kept without a span. It returns plain `StoredRecord` and `StoredValue` objects; writing them is the caller's job.

## The merge rule

`merge.py`, a port of `src/services/mock/extraction-merge.ts`. `merge_extracted_records(previous, fresh)`:

- keeps every record a person touched: human origin, or reviewed (not `suggested`), or with a value that has a human origin or was reviewed;
- drops the untouched suggestions of the earlier run;
- drops a fresh record whose span overlaps a kept record of the same record type (spans that only touch do not overlap); a record without a span blocks nothing;
- orders by span start, records without a span last, otherwise in the order given.

It works on stored `ExtractionRecord`s (with their values prefetched) as well as on `StoredRecord`s.

## Corrections

`services.change_extraction`, the one function every record write goes through (`POST .../records`, `PATCH` and `DELETE .../records/{record_id}` under a file's `extraction`). In this order: the file is in the run; the extraction exists (404 `extraction_not_found`; only the first add makes it); the `revision` the client sent is the current one (409 `revision_conflict`, `details: { revision }`); the change applies; the revision goes up by one. All or nothing: any error leaves the records as they were. The extraction row is locked while it changes, so of two writes with the same revision one succeeds and the other is a 409. Every write answers the whole extraction, as the read does, and announces `extraction.changed` on the run socket once the change is committed, never for a refused one.

A first add (`revision: 0`, no extraction yet) makes the extraction from the document's text and ETag: revision 1, 422 `upstream_not_ready` when the document has no text. What a person writes is `origin: human`, `review: accepted`, `anchored: true`. A field left out of an add, or sent with no values, stores one `null` value, `human`, `accepted` and `anchored`, as the UI's mock does. A quote and a value are kept exactly as sent, with their whitespace.

`PATCH` changes only the keys sent; `span: null` clears the span. Accepting a record accepts its values that are still `suggested`. `DELETE` is for records a person added; a model's suggestion answers 422 `not_deletable`, and is rejected instead so it is not suggested again. A record or field outside the extraction's definition version is 422 `unknown_field`, more than one value for a field with `multiple: false` is 422 `too_many_values`.

## Running the stage

Pressing Run in the Studio extracts the chosen files in the background. The request only queues the work; one job per file does it (`tasks.extract_file`, see [jobs.md](jobs.md)), and the progress reaches the UI as `cell` events on the run socket (see [realtime.md](realtime.md)).

```
POST /api/v1/runs/{run_id}/stages/extract/executions
{ "file_ids": ["..."], "config": { "definition_version": 3 } }

202 { "execution_id": "...", "stage": "extract", "file_ids": ["..."] }
```

- No `file_ids` (or `null`) means every file of the run. A file named twice runs once. The answer lists the files in the order they run.
- `config.definition_version` is the version the person saw. The UI sends it as `config.definitionVersion` today; both spellings are accepted. Left out, the latest saved version is used.

### The request

`services.start_execution`, in this order:

| Check | Answer |
| --- | --- |
| The run is the person's | 404 `run_not_found` |
| The stage is `extract` | 404 `not_found` |
| Every id is a file of this run (and the list is not empty) | 422 `unknown_file` |
| None of these files is `queued` or `running` | 409 `execution_in_progress`, `details: { execution_id }` |
| The version is the latest saved one | 409 `definition_conflict`, `details: { version }` |

Then, in one transaction: the cells of the files become `queued` with the new execution's id (through `runs.services.set_cell`, so the socket sees each), and one job per file is enqueued once that commits. A refused request changes nothing and announces nothing. The cells are locked while they are checked, so of two requests for the same file one wins.

### The job, per file

`services.run_extraction(file_id, execution_id, definition_version)`:

1. The cell must still be `queued` for this execution, otherwise the job does nothing (the file was run again, its cell was released after the timeout, or the run was deleted). The cell becomes `running`.
2. The document is read (`selectors.input_text`), with its ETag.
3. `get_extractor()` runs with that definition version and the run's example records: the records a person accepted and marked `use_as_example`, in any file of the run, without their rejected values.
4. `stored_records` checks the spans; the merge rule keeps every record a person touched, replaces the untouched suggestions and drops a fresh one that overlaps a kept record of the same type.
5. In one transaction, with the cell and the extraction locked: the cell must still be `running` for this execution (otherwise nothing is stored); the records are written; `revision` goes up by one (a first extraction is revision 1); `source_etag` is the document's ETag when it was read and `definition_version` the one used. The cell becomes `succeeded` and `extraction.changed` is announced, both once the transaction commits.

The cell's `output` is `{ name, content_type, size, etag }`: `<file name without extension>.extract.json`, `application/json`, the size of the extraction as `GET .../extraction` answers it, and `etag` `extract-<execution_id>`, new for every execution. The UI refetches the records when it changes.

### Failure

Anything that goes wrong (the document cannot be read, the extractor raises, the write fails) leaves the records exactly as they were: the write is one transaction. The failure is logged with its traceback and the cell becomes `failed` with `error: { code, message }`:

| `code` | When |
| --- | --- |
| `upstream_not_ready` | the document could not be read |
| `extraction_failed` | the extractor or the write raised; the details are only in the log |
| `execution_timeout` | the cell was left active by a dead worker (below) |

A failed cell is not active, so the file can be executed again at once.

### A dead worker

A cell left `queued` or `running` longer than `EXECUTION_TIMEOUT_SECONDS` (default 600) is released: at the next execution request or snapshot (`GET /api/v1/runs/{run_id}`) it becomes `failed` with `execution_timeout`, keeping its `execution_id`. `runs.services.release_stuck_cells` does it. If that job does finish later, its cell no longer belongs to it and it stores nothing. The time counts from the cell's last change, so `running` restarts the clock.

### States of a cell

```
pending ──POST──> queued ──job starts──> running ──stored──> succeeded
                    │                       │
                    └──timeout──> failed <──┴── error or timeout
succeeded / failed ──POST──> queued
```

### Events on the run socket, in order

| Event | When |
| --- | --- |
| `cell`, `queued` | in the request, once per file |
| `cell`, `running` | the job starts |
| `cell`, `succeeded` | the records are stored |
| `extraction.changed` (`file_id`, `revision`) | right after, in the same commit |
| `cell`, `failed` | instead of the last two, on a failure or a timeout |

| Variable | Meaning |
| --- | --- |
| `EXECUTION_TIMEOUT_SECONDS` | After how long a `queued` or `running` cell counts as failed. Default 600 |

## The shape of a definition

`definition.py` is the one place the shape of a definition is written in code: `Draft` (a prompt, record types, an output) holds `RecordType`s, a record type holds `Field`s, and `Output` says how records are written out. Each model owns its own part and its rules: the allowed modes (`quote`, `inferred`), value types (`text`, `date`, `number`, `choice`) and formats (`json`, `markdown`, `csv`); strings are trimmed; a missing or blank `id` is filled in (`rt-...`, `f-...`); a record type's fields each have a key and no two share one. The module imports nothing from Django, DRF or another app.

`validation.parse_draft(data)` is the one way in from untrusted data. It returns a `Draft`, or raises 422 `invalid_definition` with `details: { errors: [{ path, message }] }`, where `path` leads to the value (`record_types.0.fields.2.mode`; a rule of a record type, such as a repeated key, is at `record_types.0` and names the record type). `validate_draft(data)` is `parse_draft(data).model_dump()`: plain data for the database, which still stores the definition as JSON.

The OpenAPI schema is generated from the DRF serializers in `validation.py` (`DraftSerializer`), not from the models: drf-spectacular's pydantic support covers only the outermost model of a request, and the schema needs a request and a response variant of each part and a body that adds `base_version` and `note`. A test feeds the same valid and invalid samples to the serializers and to `parse_draft` and expects the same verdicts; change both when the shape changes.

## Extraction configuration and its versions

The UI and the documents call the definition an "extraction configuration". The paths, the code and the error codes keep the word `definition`.

Every save makes a new version; versions are never changed or deleted. A save may carry a `note` (up to 200 characters, longer is 422 `invalid_definition`), stored on the version. Both `GET` and `PUT .../stages/extract/definition` answer `note` and `created_at` besides the definition.

- `GET .../definition/versions` answers `{ "items": [{ version, note, created_at, record_type_count, field_count }] }`, newest first.
- `GET .../definition/versions/{version}` answers that version in the shape of the definition. An unknown version is 404 `definition_version_not_found`.
- `POST .../definition/versions/{version}/restore` saves a copy of that version as the newest one, with the note `Restored from version N`, and answers it.

All three are for the run's owner; someone else's run is 404 `run_not_found`.
