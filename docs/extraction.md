# Extraction

What turns a document into records is replaceable, and running it again never undoes a person's work. The pieces are in `apps/extraction`.

## The extractor interface

`extractors/base.py`. An extractor takes the text of a document, a `Definition` (a definition version as plain data: `version`, `prompt`, `record_types`) and the example records (accepted records marked `use_as_example`), and returns raw records: a `RawRecord` has its record type id, its span and, per field, `RawValue`s with the quotes they came from. A field that was not found is one value that is `None` with no spans. Nothing in the interface touches the database or the network.

Spans are `{start, end, quote}` and offsets count code points (Python `str` indexing, `end` exclusive).

## Choosing one

`EXTRACTOR` selects the implementation through `get_extractor()`: `scripted`, `llm` (the model extractor, below), or the dotted path of a class (how tests swap in a fake). Any other value stops the app at start.

## The scripted extractor

`extractors/scripted.py`, a port of the UI's `src/services/mock/mock-extractor.ts`; no model, the same answer every time.

- A record is a `## ` heading that starts with the record type's name (case does not matter), down to the next `## ` heading.
- A field comes from the heading (a `title` field: the text after `ADR-012: `), from a `**Label:** value` line or from a `### Label` section (down to the next heading). The label matches the field's name or key, ignoring case, `_`, `-` and runs of spaces; a `decided_on` field also matches `Date`.
- A `multiple` field on a `**Label:**` line gives one value per comma-separated item.
- A `quote` field carries the exact text and its span. An `inferred` field carries the evidence span and a tidied value: the first matching choice for a `choice` field, an ISO date for a `date` field (`3 November 2026`, `November 3, 2026`, `2026-11-03`).

The port was checked against the TypeScript: both give the same records for the sample documents, for hand-made edge cases and for 300 generated documents.

## From raw to stored records

`extractors/records.py`, `stored_records(text, raw_records)`. For one file it checks every span against the text, anchors a quote whose offsets do not fit (`spans.resolve_span`), keeps a quote that is not in the text with `anchored: false`, and marks every record and value `llm` and `suggested`. A record whose own span cannot be placed is kept without a span. It returns plain `StoredRecord` and `StoredValue` objects; writing them is the caller's job.

## The model extractor (`EXTRACTOR=llm`)

`extractors/llm.py` (`LlmExtractor`) and `extractors/llm_prompt.py`. Each part of a file (a short document is one part) is extracted with one model call, through the OpenAI Agents SDK: an `Agent` with `output_type=ModelOutput`, no tools and `max_turns=1`. The SDK sends `ModelOutput` as a strict JSON schema on the Responses API and on Chat Completions, so one code path serves `openai`, `azure` and `anthropic` (`LLM_PROVIDER`, `LLM_MODEL`; `apps.core.llm.connect()`). The answer goes through `to_raw_records`, then the usual `stored_records` and merge.

**What it sends.** The fixed instructions (`INSTRUCTIONS`), then one message: the person's prompt, the record types as JSON (id, name, description; per field key, name, description, mode, value type, choices, multiple), up to 5 example records (the accepted ones marked `use_as_example`, in the shape the model answers in) and the document inside `<document>` tags. Document text leaves the system for the configured model provider (see [security.md](security.md)).

**What it trusts.** The document is data. The instructions say nothing in it is an instruction, a closing `</document>` or `</examples>` inside it (any case, any spacing) is defused, and the model has no tools, so a planted sentence can at worst produce wrong suggestions, which a person reviews. The answer is trusted no further than `to_raw_records` trusts it (above): quotes are searched in the text, values are checked against their type and choices.

**Chunking in a configuration.** A configuration version carries `chunking`: `{"strategy": "auto"|"heading"|"paragraph"|"fixed", "size": int|null}`, next to `output`, in the body of `PUT .../definition`, in every answer that returns a configuration (`GET` and `PUT .../definition`, `.../versions/{n}`, restore) and in `definition` of a template. Rules (`Chunking` in `definition.py`): a save without the `chunking` key (a client that does not know it) keeps the chunking of the latest saved version (`auto` when there is none), while a key that is present sets it as given (`{"strategy": "auto"}` included; `null` is 422), and the assistant's request path is unchanged; `size` must be a whole number (a float, a numeric string or a boolean is 422); for `auto`, `size` is stored and returned as null whatever was sent; for the other strategies a missing size is 4000 (or `EXTRACTION_CHUNK_CHARS` if that is lower); the smallest size is `min(1000, EXTRACTION_CHUNK_CHARS)` and the largest is `EXTRACTION_CHUNK_CHARS`, and a size outside that is 422 `invalid_definition` ("The chunk size must be between 1000 and 8000 characters.", path `chunking`), as is an unknown strategy. The column is `DefinitionVersion.chunking` (JSON; default auto both in Python and in the database, so a row inserted by code that does not know the column, such as the previous release during a rolling deploy, reads as auto); a stored size outside today's range is moved into it on read and an unusable stored value reads as auto, so old versions stay readable and reading never fails. Restore and templates copy it, and the assistant's proposals keep the chunking of the definition they were made from: the scripted assistant copies it, and the model's `propose_definition` and `preview_extraction` schemas leave `chunking` out and the tool puts the draft's own value back. `extractors.base.Definition` carries it, but no extractor uses it yet.

**Limits.** `EXTRACTION_CHUNK_CHARS` (default 8000): the most document characters in one call; a longer document is split (below). Keep it well under `EXTRACTION_MAX_OUTPUT_TOKENS`: measured on `claude-haiku-5-5` with the ADR template, where most fields are quotes, the answer is about one token per document character (a 7900-character part answered with about 8000 tokens), and a 20000-character part overflowed the 16000-token answer and failed. `EXTRACTION_MAX_CHUNKS` (10): the most parts of one document. `EXTRACTION_CONCURRENCY` (4): how many calls of one file run at a time. `EXTRACTION_FILE_TIMEOUT_SECONDS` (480, keep it below `EXECUTION_TIMEOUT_SECONDS`): all the calls of one file together. `EXTRACTION_MAX_INPUT_CHARS` (60000): the most characters of the whole message (prompt, record types, examples and document part); a larger one fails before any call. Each example value and quote is cut to 300 characters, with at most 20 values per example and 3 quotes per value. `EXTRACTION_MAX_OUTPUT_TOKENS` (16000): the answer's size. It is sent as `max_tokens` (`anthropic`), `max_output_tokens` (`openai`) or `max_completion_tokens` (`azure`, because newer Azure deployments refuse `max_tokens`). On a reasoning deployment that limit also counts the model's reasoning tokens, so less of it is left for the answer: raise it or lower `EXTRACTION_CHUNK_CHARS` if answers are cut off. When a call fails, `extraction_model_failed` logs the error's class, HTTP status and the provider's error `code`, `param` and `type` (each cut to 80 characters), never the message or body. `EXTRACTION_MODEL_TIMEOUT_SECONDS` (120): one call. The SDK's tracing is off, nothing is stored by the provider (`store=False`), and the client is closed after each call.

**Failures.** An `ExtractionError(message)` (in `extractors/base.py`) fails the cell with code `extraction_failed` and its message; any other exception keeps "The extraction failed.".

| Message | Cause |
| --- | --- |
| No language model is configured for extraction. | `missing_settings()` is not empty |
| The language model could not be reached. | the model or the sign-in failed |
| The language model's answer could not be used. | an invalid, refused or cut-off answer, or a call or the whole file (`EXTRACTION_FILE_TIMEOUT_SECONDS`) timed out |
| This document is too long to extract. | more than `EXTRACTION_MAX_CHUNKS` parts; no call is made |
| This definition is too large to extract with. | the whole message is longer than `EXTRACTION_MAX_INPUT_CHARS` |

At start, `EXTRACTOR=llm` with settings missing gives the warning `extraction.W001` naming them; the app still starts. `extraction.W002` warns when `EXTRACTION_FILE_TIMEOUT_SECONDS` is not below `EXECUTION_TIMEOUT_SECONDS`, or when `EXTRACTION_MAX_CHUNKS` parts cannot finish in it. In the assistant's `preview_extraction` tool an `ExtractionError` is the tool's `Error: <message>` text.

**Cost.** One call per part (at most `EXTRACTION_MAX_CHUNKS` per file), each: the input is about the instructions (roughly 500 tokens), the definition, the examples and the document. The limits count characters, not tokens: English is about 1 token per 4 characters (about 2000 tokens for the default part), but CJK, emoji or rare-script text can cost 1 to 3 tokens per character, so the worst case for 8000 characters is about 24000 tokens, and the whole message is capped at `EXTRACTION_MAX_INPUT_CHARS` characters; the output is the quotes and values of every record. The job's span has `extraction.chunks`, the number of parts. Each call logs `extraction_model_call` and adds an `extraction.model_call` event to the job's span with the model name, input and output tokens, the number of records and the duration ([observability.md](observability.md)).

**Trying it.** `uv run python manage.py try_extractor --run <run_id> [--file <name>]` runs the configured extractor on the run's files with its latest definition and examples and prints each record (type, span) and each field's value, and whether its quote was found. It stores nothing. With `EXTRACTOR=llm` it calls the model and costs tokens.

### Long documents

`extractors/chunks.py`, `split(text, limit)`, pure: the parts of a document as `(start, end)` offsets that cover the text exactly, in order, without overlap, each at most `limit` (`EXTRACTION_CHUNK_CHARS`) characters. Each part ends at the best boundary within the limit, in this order: before a heading line (`#` at the start of a line; a heading in the second half of the part is preferred, so a title near the top does not make a tiny part; then the highest level present, the last one of that level), after a blank line, after a line end, after a space; a hard cut only when a run has none. Every part is one model call with the same instructions, definition and examples, at most `EXTRACTION_CONCURRENCY` at a time. `to_raw_records(text, definition, output, start, end)` looks for each part's quotes only in that part, so a quote that also occurs in an earlier part is placed in its own; the records are joined in document order. All or nothing: if one part fails, the other calls are cancelled and the file fails with nothing stored. More than `EXTRACTION_MAX_CHUNKS` parts fails before any call.

An empty document has no part and makes no call. Each call's `extraction.model_call` event is added as the call finishes, so a file that fails keeps the events of the parts that completed. The assistant's `preview_extraction` is bounded separately, as its reply is cut at 120 seconds: at most `EXTRACTION_PREVIEW_MAX_CHUNKS` parts (default 2, longer fails with the too-long message) and `EXTRACTION_PREVIEW_TIMEOUT_SECONDS` (default 100).

**Known limit.** A record that crosses a cut is found in pieces (two records, each with part of the fields) or missed. Parts do not overlap and no context is shared between them, so a field in one part cannot be tied to a record in another.

## From a model's answer to raw records

`apps/extraction/extractors/llm_output.py` is the pure half of an extractor that calls a model: no model, no network, no database. The model answers with `ModelOutput { records: [ModelRecord { record_type_id, starts_with, values: [ModelValue { field_key, value, quotes }] }] }` (every key required, so strict JSON schema mode accepts it). It returns quotes, not offsets: a model copies words reliably and counts characters badly.

`to_raw_records(text, definition, output, start=0, end=None)` finds the quotes in the text and gives the real offsets (code points, into the whole `text`; `start`/`end` limit where records are looked for). Nothing in the answer is trusted:

- Unknown record types and unknown field keys are dropped.
- A record starts at the first `starts_with` after the previous record's start (records that open with the same words are found one after the other); its region runs to the next record's start. A quote is looked for in its record's region, then anywhere in `start..end`; one not found becomes `Span(0, 0, quote)`, which `stored_records` stores as not anchored.
- A `quote` field's value is the quote; an `inferred` field's value must fit its type (choice, `YYYY-MM-DD` date, number) or counts as not found. A field that is not `multiple` keeps its first value.
- Every field of the record type gets at least one `RawValue`, in definition order; the record's span covers its start and found quotes; a record with no found start and no value is dropped; at most 1000 records are kept (for a file of several parts, in all).

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
| `extraction_failed` | the extractor or the write raised; the details are only in the log. An `ExtractionError` puts its readable message in the cell |
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

`definition.py` is the one place the shape of a definition is written in code: `Draft` (a prompt, record types, an output and a chunking) holds `RecordType`s, a record type holds `Field`s, and `Output` says how records are written out. Each model owns its own part and its rules: the allowed modes (`quote`, `inferred`), value types (`text`, `date`, `number`, `choice`) and formats (`json`, `markdown`, `csv`); strings are trimmed; a missing or blank `id` is filled in (`rt-...`, `f-...`); a record type's fields each have a key and no two share one. The module imports nothing from DRF or another app; from Django it reads only `settings.EXTRACTION_CHUNK_CHARS`, for the largest chunk size.

`validation.parse_draft(data)` is the one way in from untrusted data. It returns a `Draft`, or raises 422 `invalid_definition` with `details: { errors: [{ path, message }] }`, where `path` leads to the value (`record_types.0.fields.2.mode`; a rule of a record type, such as a repeated key, is at `record_types.0` and names the record type). The database still stores the definition as JSON: `parse_draft(data).model_dump()`.

The OpenAPI schema is generated from the DRF serializers in `validation.py` (`DraftSerializer`), not from the models: drf-spectacular's pydantic support covers only the outermost model of a request, and the schema needs a request and a response variant of each part and a body that adds `base_version` and `note`. A test feeds the same valid and invalid samples to the serializers and to `parse_draft` and expects the same verdicts; change both when the shape changes.

## Extraction configuration and its versions

The UI and the documents call the definition an "extraction configuration". The paths, the code and the error codes keep the word `definition`.

Every save makes a new version; versions are never changed or deleted. A save may carry a `note` (up to 200 characters, longer is 422 `invalid_definition`), stored on the version. Both `GET` and `PUT .../stages/extract/definition` answer `note` and `created_at` besides the definition.

- `GET .../definition/versions` answers `{ "items": [{ version, note, created_at, record_type_count, field_count }] }`, newest first.
- `GET .../definition/versions/{version}` answers that version in the shape of the definition. An unknown version is 404 `definition_version_not_found`.
- `POST .../definition/versions/{version}/restore` saves a copy of that version as the newest one, with the note `Restored from version N`, and answers it.

All three are for the run's owner; someone else's run is 404 `run_not_found`.

## Templates

A template is a complete extraction configuration to start from: a prompt, record types with their fields, and an output (format and template text). It is a `Draft` with an `id`, a `name` and a `description` that says what it is for. The built-in ones are `adr` (the default, named in `DEFAULT_TEMPLATE_ID`), `skill` (one agent skill per record, written out as `SKILL.md`), `policy-rule` (one rule of a policy per record, as JSON) and `blank` (nothing set up).

`GET /api/v1/definition-templates` answers `{ "items": [{ id, name, description, definition }], "next": null }`, the default first, then by name, for signed-in people. `template_registry.get_template(id)` raises 404 `template_not_found` for an unknown id. A run that says nothing starts with the default template's definition (`selectors.get_definition`), as the scripted assistant does when it sets up ADRs.

To add one, put a file `apps/extraction/templates/<id>.json` with `{ "id", "name", "description", "definition": { "prompt", "record_types", "output", "chunking" } }` (`chunking` is optional: auto). The id is the file name. Write the ids of record types and fields in the file and keep them: loading a template twice gives the same ids, and no id is used in two files. Run `uv run pytest apps/extraction/tests/test_templates.py`: it names the file and the problem (a file that does not parse, an id or field key used twice, a `{{key}}` in the output template that is not a field key). The files are read when the app starts, so a broken one stops the server too.

Not there yet: a person's own templates (no table, no saving), and choosing a template when a project or run is created.
