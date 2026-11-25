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

**Chunking in a configuration.** A configuration version carries `chunking`: `{"strategy": "auto"|"heading"|"paragraph"|"fixed"|"custom", "size": int|null, "custom": object|null}`, next to `output`, in the body of `PUT .../definition`, in every answer that returns a configuration (`GET` and `PUT .../definition`, `.../versions/{n}`, restore) and in `definition` of a template. Rules (`Chunking` in `definition.py`): a save without the `chunking` key (a client that does not know it) keeps the chunking of the latest saved version (`auto` when there is none), while a key that is present sets it as given (`{"strategy": "auto"}` included; `null` is 422), and the assistant's request path is unchanged; `size` must be a whole number (a float, a numeric string or a boolean is 422); for `auto`, `size` is stored and returned as null whatever was sent; for the other strategies a missing size is 4000 (or `EXTRACTION_CHUNK_CHARS` if that is lower); the smallest size is `min(1000, EXTRACTION_CHUNK_CHARS)` and the largest is `EXTRACTION_CHUNK_CHARS`, and a size outside that is 422 `invalid_definition` ("The chunk size must be between 1000 and 8000 characters.", path `chunking`), as is an unknown strategy. The column is `DefinitionVersion.chunking` (JSON; default auto both in Python and in the database, so a row inserted by code that does not know the column, such as the previous release during a rolling deploy, reads as auto); a stored size outside today's range is moved into it on read and an unusable stored value reads as auto, so old versions stay readable and reading never fails. Restore and templates copy it, and the assistant's proposals keep the chunking of the definition they were made from: the scripted assistant copies it, and the model's `propose_definition` and `preview_extraction` schemas leave `chunking` out and the tool puts the draft's own value back. `extractors.base.Definition` carries it, and the model extractor uses it (below).

**Chunking strategies (the model extractor).** `LlmExtractor` cuts a document with the configuration's `chunking` (`split_by` in `extractors/chunks.py`), for a run and for the assistant's preview alike. `auto` is today's cutter (`split`) with `EXTRACTION_CHUNK_CHARS` as the size and behaves as before. `heading` cuts at Markdown headings (the library `MarkdownSplitter`), `paragraph` at paragraphs, lines and sentences (`TextSplitter`), `fixed` in windows of the size, at the last whitespace of the window's second half, else a hard cut. A size other than auto is capped at run time by `EXTRACTION_CHUNK_CHARS` (an older configuration, or a lowered setting, never sends a larger part). Records of a later part carry their quote positions in the whole document, as before.

*Limits.* The parts of a document are at most `EXTRACTION_MAX_CHUNKS` per run (10) and `EXTRACTION_PREVIEW_MAX_CHUNKS` per preview (2), and a part is never longer than the size, so the longest document shrinks with the size: at most `parts x size` characters (run: 10,000 at size 1000, 40,000 at 4000, 80,000 at 8000; preview: 2,000, 8,000, 16,000). The check comes before the split: a text longer than `parts x size` fails with the too-long message without calling the splitter (the library strategies take quadratic time on a long run without whitespace, such as 1 MB of `#`). This loses nothing: a split needs at least `ceil(length / size)` parts. For `auto` the size is `EXTRACTION_CHUNK_CHARS`. With every strategy parts can be shorter than the size, so a shorter text can still need too many parts and fail after the split. For a strategy other than auto the message says the document is too long for the chosen chunk size and that a larger chunk size, or the Automatic strategy, may allow a longer document (not when the size is already the largest); for `auto` it is the plain "This document is too long to extract." A text with a lone surrogate (possible in a JSON body) fails `heading` and `paragraph` with "This document contains characters that cannot be read.". The scripted extractor does not split: it reads the whole text and ignores the chunking.

**Custom chunking (prototype).** The strategy `custom` cuts a document with Python code that a sandbox agent wrote from the person's words. It exists to find out whether that is worth building; it is off by default and is not for production.

- *Setting.* `CUSTOM_CHUNKING=off|local` (default `off`); `local` also needs `AUTH_MODE=dev` (any signed-in person can save code as a configuration's chunking, so on a shared server this would be code execution for everyone), and production settings refuse it; both stop at start. `CUSTOM_CHUNKING_GENERATE_TIMEOUT_SECONDS` (120) bounds writing the code, `CUSTOM_CHUNKING_RUN_TIMEOUT_SECONDS` (10) bounds one run of the code on one document, `CUSTOM_CHUNKING_MAX_TURNS` (12) bounds the agent's turns.
- *In a configuration.* `chunking.custom` is `{instruction (1 to 2000 characters), source_url (null or at most 2000), code (1 to 20000), summary (at most 1000)}` when the strategy is `custom` and null for every other strategy (whatever was sent is dropped); the answers always carry the key. `custom` without code is 422 `invalid_definition` ("Generate and apply the splitting code first."); the size is sized like `fixed`. A stored `custom` block that cannot be read reads as `auto`. Saving a `custom` chunking while the setting is `off` is allowed; the run then fails (below). The assistant neither sees nor changes the chunking, as for the other strategies, and its proposals and the restore keep the block.
- *Generate.* `POST /api/v1/runs/{run_id}/stages/extract/chunking/generate` with `{instruction, source_url?, size?}` answers `{code, summary, documents: [{file_id, name, characters, parts: [{start, end, starts_with}]}]}` and saves nothing: the person applies the result in the draft and saves the configuration. It is synchronous (typically 15 to 60 seconds). Errors: 409 `custom_chunking_off`, 409 `model_not_configured`, 422 `validation_error` (a refused link, under `source_url`), 422 `custom_chunking_failed`, 504 `custom_chunking_timeout`, 502 `model_unreachable`; someone else's run is 404.
- *The agent* (`custom_chunking/author.py`). A `SandboxAgent` with only the `Shell` capability, on the model of `LLM_PROVIDER` (Chat Completions for Azure and Anthropic: shell tools are function tools there; the `Filesystem` capability uses a custom tool and is not used). Its workspace holds the run's documents (at most 5, each cut to 60,000 characters), a trusted `check.py` and `reference.md` when a link was given. It writes `splitter.py` with `def split(text: str, size: int) -> list[tuple[int, int]]` (ranges in order from 0, no gap, no overlap, none empty, none longer than `size`, ending at `len(text)`; standard library only) and runs the checker until it prints OK. The documents and the reference are told to be data, not instructions. After the run the server reads `splitter.py` back and runs it itself on every document (`run_splitter`); the agent's claim is never trusted. `starts_with` is the first non-empty line of the part, cut to 80 characters, taken by the server from the document.
- *The link* (`custom_chunking/fetch.py`). The server fetches `source_url`, never the sandbox: https on the standard port only, no credentials in the link, the host must resolve to public addresses only (private, loopback, link-local, reserved, multicast and unspecified addresses, IPv4 and IPv6, and IPv4 addresses wrapped in IPv6), the connection goes to the checked address (the host name stays the TLS name, so DNS cannot be swapped between check and connect), no proxy from the environment, no redirects, 10 seconds, at most 500 KB read, text content types only, HTML turned into rough plain text and cut to 20,000 characters. A refusal is 422 on `source_url` with a short reason.
- *Running.* `LlmExtractor` calls `run_splitter` (`custom_chunking/sandbox.py`) with the saved code instead of a library strategy: a fresh temporary workspace per document holding `splitter.py`, the text and a small runner, started by `custom_chunking/process.py` with the interpreter in isolated mode (`-I`), its own process group (killed when the run ends, times out or is cancelled, so a looping splitter cannot outlive a cancelled request), `RLIMIT_CPU` (the time limit plus 2 s), `RLIMIT_AS` (2 GB) and `RLIMIT_FSIZE`, the time limit above, and no network where `unshare -rn` works (probed once; otherwise one warning `custom_chunking_network_open` is logged and the code runs with the server's network). The runner closes stdout and stderr, so what the code prints goes nowhere. The ranges are parsed strictly and checked with the rule of the built-in strategies. An empty text makes no parts and starts nothing. The `limit x size` guard and `EXTRACTION_MAX_CHUNKS` apply as for every strategy. The assistant's preview uses it too. A failure fails that document with "The custom splitting code failed on this document.", a timeout with "The custom splitting code took too long on this document." and, with the setting `off`, "Custom chunking is turned off on this server."
- *The agent's commands.* The agent's only tool is `exec_command`, replaced by a limited one (`ConfinedExecTool`): each command stops after 15 s, at most 64 KB of output is kept (the rest is dropped as it arrives, so memory stays bounded), there is no terminal, no stdin tool and nothing keeps running after the command (the process group is killed), and the same `unshare -rn` applies.
- *Refused before the agent runs.* A run with no documents with text is 422 `validation_error`, message "Add a document first: the splitting code is tested on the project's documents." (also under `details.documents`). A text or code that cannot be written as UTF-8 and any unforeseen sandbox error are 422 `custom_chunking_failed`.
- *No isolation.* The code the agent writes and the agent's commands run as the server's own user and can read whatever that user can: the server's environment (`/proc/<pid>/environ`), `.env`, signing keys, the home directory. The network is cut only where `unshare` works (not in a default Docker container, where user namespaces are usually blocked). The time and resource limits are not a security boundary. Generate sends up to 5 documents (60,000 characters each) and the linked page to the model provider, and a document or a linked page could steer the agent (prompt injection; it is told they are data, which is no guarantee). That is why this is a prototype for a single developer machine with trusted documents and links only, off by default, needing `AUTH_MODE=dev` and refused in production; see [security.md](security.md). A real isolated sandbox (a container or a hosted one) would replace `process.py`.
- *Limits.* A document is shown to the agent up to 60,000 characters, so the code is written from the start of a long document; it is checked on the whole of every document (at most 5). Writing the code costs one model call per turn, up to `CUSTOM_CHUNKING_MAX_TURNS`.

*Changing the strategy.* A change of chunking is a new configuration version like any other change. Records already stored do not change: they change only when the document is run again with the new version, and the merge rule then keeps the records a person touched (accepted, rejected, edited or used as an example) and replaces the rest. The long sample `enriched/engineering/architecture/engineering-decision-log-2026.md` (about 14,000 characters, nine ADRs) shows the effect: at size 4000, `auto` gives 5 parts, `heading` 6, `paragraph` 4, `fixed` 4; at 8000, 2, 3, 2, 2.

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
