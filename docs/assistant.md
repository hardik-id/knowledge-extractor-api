# Assistant

The Studio's chat turns a bare prompt into fields and a template, and adjusts them on request. The assistant proposes; the person applies. The brain behind the chat is an agent, and agents are replaceable. This page covers the conversation API, the reply job, the agent interface, the scripted agent and the LLM agent.

## The conversation

A run has one conversation. Each message is stored (`apps/assistant/models.py`, `Message`):

```json
{
  "id": "01a1f141-…",
  "role": "assistant",
  "text": "I set this up for architecture decision records: …",
  "proposal": { "definition": { "prompt": "…", "record_types": [], "output": { "format": "markdown", "template": "…" } },
                "reasons": [{ "path": "ADR / Title", "reason": "Copied exactly from the text. …" }] },
  "status": "done",
  "created_at": "2026-11-19T10:00:00Z"
}
```

`role` is `user` or `assistant`. `status` is `streaming` while a reply is being written, then `done`; a person's message is `done` at once. `proposal` is `null` when there is none, and always `null` on a person's message. The proposal's `definition` has the shape of a saved definition without `version`, as `validate_draft` returns it.

| Call | Body | Answer |
| --- | --- | --- |
| `GET /api/v1/runs/{run_id}/extraction/assistant/messages` | none | 200 `{ "messages": [message] }`, oldest first |
| `POST /api/v1/runs/{run_id}/extraction/assistant/messages` | `{ "text", "definition" }` | 201, the stored **user** message (one object) |
| `DELETE /api/v1/runs/{run_id}/extraction/assistant/messages` | none | 204, every message of the run removed; the run's sockets get `{ "type": "assistant.cleared" }` after the commit. Nothing else changes (not the definition, not the records). 409 `assistant_busy` while a reply is `streaming` (a stale one is closed first) |

The POST body's `definition` is the draft on the person's screen, saved or not, without `version`. It goes through `validate_draft` and is kept with the person's message: the agent works from it, not from the last saved version. The text is stored without leading and trailing spaces.

| Status | Code | When |
| --- | --- | --- |
| 404 | `run_not_found` | the run is not the caller's, or does not exist |
| 422 | `empty_message` | `text` is missing, empty or only spaces |
| 422 | `invalid_definition` | `definition` is missing or not a valid draft |
| 422 | `validation_error` | `text` is not a string |
| 409 | `assistant_busy` | a reply on this run is still `streaming` |

In the same transaction as the person's message, the POST stores the assistant's reply, empty and `streaming`, and enqueues the reply job with the reply's id (after the commit, `docs/jobs.md`). A run has at most one reply streaming: the database refuses a second one (`one_reply_at_a_time`), so two POSTs at the same moment cannot both start one.

The assistant proposes and the person applies: nothing here saves a definition. Applying a proposal is a normal `PUT` of the definition.

## The reply job

`write_reply(message_id)` in `apps/assistant/tasks.py`. It loads the reply and the message it answers, then runs `get_agent().reply(text, definition, history, workspace)`:

- `history` is the run's earlier messages, oldest first.
- `workspace` is what the agent can look at: the run's documents, what was extracted from them and a dry run of the extractor (below), all as the run's owner.

Each event of the agent is stored first and announced after, on the run's socket through `apublish_run_event` (`docs/realtime.md`), so a client that missed events reads the same from `GET`:

| Agent event | Stored | Sent |
| --- | --- | --- |
| `TextDelta(text)` | appended to the reply's `text` | `{ "type": "assistant.delta", "message_id", "text" }` |
| `Proposal(definition, reasons)` | the reply's `proposal`, the definition through `validate_draft` | `{ "type": "assistant.proposal", "message_id", "proposal": { "definition", "reasons" } }` |
| end of the stream | `status` becomes `done` | `{ "type": "assistant.done", "message_id" }` |

Every write changes the reply only while it is `streaming`. Once it is done (or gone, with its run) the job stops.

### A reply always ends

- **The agent fails** (raises, or proposes a definition that is not valid): the reply gets one sentence, "Sorry, something went wrong and I could not finish this reply.", after whatever it had written, and becomes `done`. The sentence goes out as an `assistant.delta`, then `assistant.done`. A proposal already sent stays.
- **The worker died**: a reply still `streaming` `ASSISTANT_REPLY_TIMEOUT_SECONDS` after it was created is closed the same way on the next `GET` or `POST` on its run, and no longer counts as busy.
- **The job runs twice**: a reply that is done is left alone. A reply that already has text or a proposal was started by an earlier run that died; it is closed the same way, because the deltas it sent cannot be taken back.

| Variable | Meaning | Default |
| --- | --- | --- |
| `ASSISTANT_REPLY_TIMEOUT_SECONDS` | how long a reply may stay `streaming` before it counts as dead | `300` |

## The interface

In `apps/assistant/agents/base.py`. An agent implements one method:

```python
def reply(text, definition, history, workspace) -> AsyncIterator[AgentEvent]
```

| In | Meaning |
| --- | --- |
| `text` | What the person wrote. |
| `definition` | The definition on their screen, a validated draft (`apps/extraction/validation.py`), saved or not. Snake case, ids filled in. |
| `history` | The conversation so far, oldest first, as `Message(role, text)`. |
| `workspace` | `Workspace`: the read-only view of the run (next section). |

Out: a stream of events. `TextDelta(text)` is new text, not the text so far, so the deltas joined are the reply. `Proposal(definition, reasons)` is a complete definition (not a patch) and `[{ path, reason }]`; there is at most one, after the deltas. The stream ends when the reply is complete. An agent never saves anything: applying a proposal is a normal save of the definition.

Implement it as an `async def` that `yield`s. `apps/assistant/tests/fakes.py` has a fake agent in a few lines.

## The workspace

`Workspace` (`apps/assistant/agents/base.py`) is the one view of a run an agent has, and the only way a tool reaches data. All of it is async and read-only:

| Call | Gives |
| --- | --- |
| `documents()` | the run's documents, `DocumentRef(id, name)`, by name |
| `read(document_id)` | the text of one of them |
| `extractions()` | one `FileRecords(document_id, name, definition_version, records)` for each file of the run that has been extracted, by file name |
| `preview(definition, document_id)` | the `RecordView`s the configured extractor (`get_extractor()`) finds in that document with that definition |

A `RecordView` is `(record_type_id, origin, review, values)`; a `ValueView` is `(field_id, value or None, origin, review, anchored)`. `origin` is `llm` or `human`, `review` is `suggested`, `accepted` or `rejected`. These are plain frozen dataclasses: no model instance reaches an agent, and nothing in the workspace writes.

`extractions()` shows what is stored now: what a run of the extractor stored, and what people did after it (accepted, rejected, records added by hand), because a correction through the API changes the same rows.

`preview` is a dry run. It validates the draft (`invalid_definition` when it is not valid), runs the extractor on the document's text with the run's example records, checks the result as a real execution does (`stored_records`) and merges it into an empty extraction, so it returns what an execution with the same definition and text would store for a file with no earlier records. Nothing is stored, no cell changes and nothing is announced. Work a person already did on the file is not merged in.

Limits:

- It is limited to the run and its owner. `OwnerWorkspace` (`apps/assistant/selectors.py`) reads through `apps.documents.selectors` and `apps.extraction.selectors`, as the run's owner. A document id that is not one of the run's documents is `document_not_found` for `read` and `preview`, even when the owner could open that document elsewhere.
- It reads the database each time it is asked, so what an agent sees is as old as the call.
- A preview runs the extractor once per call. With a model-backed extractor that costs a model call, so a tool should bound how often it asks.
- `tests/fakes.py` has `FakeWorkspace` for tests of agents and tools.

## The scripted agent

`apps/assistant/agents/scripted.py` ports the UI's `src/services/mock/mock-assistant.ts`: keyword rules, no model, no key, deterministic. It does not read the documents. The header comment of the module lists what it understands. A bare prompt (a definition with no record types) proposes record types and fields; "add", "remove", "rename", "make exact", "make inferred", "split", "can have several values", "output as ..." and "use ... in the template" change the definition; anything else answers with help and no proposal. Proposals have unique keys, a choice field has a choice, and they pass `validate_draft`.

Its reply text is cut into deltas of three words each.

## Choosing the agent

| Setting | Values | Default |
| --- | --- | --- |
| `ASSISTANT_AGENT` | `scripted`, `openai` | `scripted` |

`get_agent()` in `apps/assistant/agents/registry.py` reads it. An unknown value stops the app at start with a message naming the setting. A value with a dot is read as the dotted path of a class, which is how tests swap in a fake.

## The LLM agent

`ASSISTANT_AGENT=openai` chooses the package `apps/assistant/agents/openai_sdk/`, an agent built with the [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/) (`openai-agents`). It reads the request, the definition on the person's screen, the conversation and, when it wants to, samples of the run's documents, explains itself and proposes a definition.

- **Text.** The model's streamed text becomes `TextDelta`s as it arrives. When the model speaks again after a tool call, the new text starts after a blank line.
- **The proposal** is a call of the tool `propose_definition(definition, reasons)`. Its arguments are checked against a strict JSON schema (the shape of `validate_draft`: modes, value types and formats as enums) and then by `validate_draft`. An invalid proposal goes back to the model as the tool's answer, starting `Error:` and saying what is wrong (where it does not fit the schema, without echoing the values), so it can correct it in the next turn. The first valid proposal is kept and later calls are refused, so at most one reaches the person, after all the text. A record type or field with an empty `id` gets one from `validate_draft`; the instructions tell the model to keep the ids of what stays.
- **`preview_extraction(definition, document_id)`** validates the definition as `propose_definition` does, runs `Workspace.preview` and summarises it: records per record type; per field the records where it was found, not found, or found but not anchored; up to three example values. Nothing is saved and it is not a proposal.
- **`read_document(document_id)`** reads a sample of one of the run's documents, through `Workspace.read` (as the run's owner, only the run's own files).
- **`find_in_documents(text)`** searches the run's documents for a literal phrase (2 to 100 characters, case does not matter, no patterns). Per matching document it gives the number of matches and up to 3 snippets of about 120 characters (12 in total, the first 50 documents searched), as untrusted data. No match is a plain answer, not an error.
- **`outline_document(document_id)`** shows how one document is built without reading it: the front matter keys, the headings with their levels, the labelled lines (`**Label:** value`) by label with a count and one example, and the length. Lists are capped (60 headings, 20 labels, 30 keys) and say when they are cut. The parsing is the pure function `outline(text)` in `tools/_structure.py`.
- **`summarize_records()`** summarizes what the run extracted, through `Workspace.extractions`: over the run and per document, per record type the records (by review, and added by hand) and per field the values found, not found and found but not anchored, how they were judged, what was added or changed by hand, and up to two rejected values as examples, clipped and wrapped as untrusted data. Found plus not found is the records of the type. With nothing extracted it says so, as a plain answer.
- **`survey_documents()`** takes no arguments and looks at the run's documents together (the first 50; it says how many were not looked at), built on `outline(text)`. Heading patterns with the number of documents and occurrences (a number or id in a heading is folded: `ADR-012: ...` and `ADR-013: ...` are `## ADR-#: …`), labels with the documents they appear in and how often, and front matter keys with up to 3 distinct values; most widespread first, what occurs in one document only below. Documents that share nothing get a plain answer saying so. The tool's description tells the model that a pattern that repeats within documents is a candidate record type and a label that comes with it a candidate field.
- **Propose, never apply.** The instructions explain the definition model (record types, fields, `quote` against `inferred`, value types, `multiple`, the output template) and the rule that the assistant proposes and the person applies. No tool saves anything.

### What the agent can look at

| Tool | Gives the model | Limits |
| --- | --- | --- |
| `read_document(document_id)` | the first 4,000 characters of one document | at most 4 reads per reply |
| `outline_document(document_id)` | front matter keys, headings, labels with counts and an example, length | 60 headings, 20 labels, 30 keys; values clipped to 60 characters |
| `survey_documents()` | heading patterns, labels and front matter keys across documents, with counts | 50 documents, 15 patterns, 20 labels, 20 keys, 3 values per key |

Both wrap what comes from a document as untrusted data.

### The package

```
apps/assistant/agents/openai_sdk/
  __init__.py        exports OpenAIAgent
  agent.py           build_agent(model): instructions + tools + model. Nothing else
  instructions.py    the instructions text
  inputs.py          the conversation as the model gets it (build_input)
  models.py          model access: missing_settings(), connect(), the Azure sign-in
  runner.py          OpenAIAgent: runs one reply, turns SDK events into TextDelta and Proposal, limits, endings
  context.py         ReplyContext: what the tools of one reply share
  tools/
    __init__.py            TOOLS, and the rules of a tool
    _shared.py             what every tool uses (as_data, clip, error)
    _definition_schema.py  the schema of a definition
    propose_definition.py
    read_document.py
    outline_document.py
    _structure.py          outline(text): front matter, headings, labels (pure)
    summarize_records.py
```

### Adding a tool

1. Write `tools/<name>.py` that exports `TOOL` (a `function_tool` or a `FunctionTool`). Read the rules in the docstring of `tools/__init__.py` first: a tool reads through the `ReplyContext`, returns bounded text, reports a failure as text starting `Error:`, and wraps document text as untrusted data.
2. Import it in `tools/__init__.py` and add `<name>.TOOL` to `TOOLS`.
3. Say in `instructions.py` when to use it, and add a test module under `apps/assistant/tests/openai_sdk/`.

Nothing else changes: `build_agent` takes whatever `TOOLS` holds.

### Configuration

| Variable | Meaning | Default |
| --- | --- | --- |
| `LLM_PROVIDER` | `openai` or `azure` | `openai` |
| `LLM_MODEL` | the model (`openai`) or the deployment name (`azure`) | empty |
| `OPENAI_API_KEY` | the key, for `openai`. A secret: in your own `.env` or the platform's secret store only | empty |
| `AZURE_OPENAI_ENDPOINT` | the resource, for `azure`, e.g. `https://my-resource.openai.azure.com/` | empty |

- **OpenAI**: `LLM_PROVIDER=openai`, `LLM_MODEL` and `OPENAI_API_KEY`. The agent uses the Responses API with `store` off.
- **Azure OpenAI**: `LLM_PROVIDER=azure`, `LLM_MODEL` (the deployment) and `AZURE_OPENAI_ENDPOINT`. There is no key: the app signs in with its own identity through `azure-identity` (`DefaultAzureCredential`, scope `https://cognitiveservices.azure.com/.default`). In Azure that is the app's managed identity; locally it is the developer's sign-in (`az login`, `azd auth login`, or the other sources `DefaultAzureCredential` tries). The identity needs the role *Cognitive Services OpenAI User* on the resource. The agent calls the resource's v1 API (`<endpoint>/openai/v1/`, no `api-version`) with Chat Completions, which every deployment serves.

**Not configured** (`ASSISTANT_AGENT=openai` and a setting above missing): the system check `assistant.W001` warns when the app or the worker starts (`manage.py check`, `migrate`, `runserver`, `db_worker`) and names the missing settings. Nothing crashes: each reply is one sentence, "No language model is configured for the assistant yet, so I cannot answer.", then `assistant.done`.

The SDK's own trace export to OpenAI is switched off (`set_tracing_disabled(True)`, and `tracing_disabled` on every run). Our own spans come with #154.

### What is sent to the model

| What | Limit |
| --- | --- |
| The instructions (the definition model and the rules) | fixed text |
| The earlier turns of the conversation | the last 20, each cut at 2,000 characters |
| The definition on the person's screen, as JSON | whole |
| The run's documents: id and name only | the first 50 (a name cut at 200 characters) |
| What the person wrote | whole |
| A sample of a document, only when the model calls `read_document` | the first 4,000 characters, at most 4 reads per reply |
| Snippets, only when the model calls `find_in_documents` | the phrase 2 to 100 characters; 3 snippets per document, 12 in all, 50 documents |
| What a definition would extract, only when the model calls `preview_extraction` | counts per field and up to 3 example values of 120 characters, at most 3 previews per reply |

**Document text is untrusted input.** The instructions say so; a sample comes back between `<document>` and `</document>` with a note to treat it as data, and a `</document>` inside the text is broken up so it cannot close the element. Document text never reaches the instructions or the tools: the tools, the schema and the rule "propose, never apply" are fixed in code, and whatever a document says, the only way to change anything is a proposal the person must apply.

### Limits of a reply

| Limit | Value | When it is reached |
| --- | --- | --- |
| Turns (model calls, tool round trips included) | 8 | the reply is cut off |
| Tool calls (all tools together, refused ones too) | 12 | the call answers `Error:` and tells the model to work with what it has |
| Result of a tool | 8,000 characters | the result is cut and ends with a note saying so |
| Time per reply | 120 s (below `ASSISTANT_REPLY_TIMEOUT_SECONDS`) | the reply is cut off |

A reply that is cut off ends with "I had to stop here because this reply took too long; please ask again, perhaps for less at once." A model or sign-in error (a wrong key, no network, no Azure identity) ends it with "I could not reach the language model, so I could not finish this reply." A valid proposal made before either still arrives. Either way the reply ends normally with `assistant.done`.

Every tool is declared through `declare` in `tools/_shared.py`, which applies the two limits above on top of a tool's own, turns an exception a tool did not expect into `Error: this tool failed` (logged as `assistant_tool_failed` with the tool and the kind of the failure, never its message) and records an `assistant.tool` span and the `assistant.tool.calls` count (see [observability.md](observability.md)).

### Logs

The agent logs what happened, never what was said: `assistant_not_configured` (the missing setting names), `assistant_reply_cut_off` (`reason`: `timeout` or `max_turns`), `assistant_model_failed` (the error's class and HTTP status, not its message, which can quote the request or a masked key) and `assistant_proposals_rejected` (a count). The SDK's own logging of model and tool data stays off (its default), and the `openai`, `httpx2` and `httpcore2` loggers never log below `INFO`, whatever `LOG_LEVEL` says: at `DEBUG` they would write request bodies and response headers. No key, token, prompt or document text reaches the logs.

### Helping a subject-matter expert

The person knows the subject, not the system. The instructions (`instructions.py`: the definition model, then the method, then the rules) make the agent work like a patient colleague:

1. **Look before proposing.** `survey_documents` when the definition is empty or the question is what can be extracted; `outline_document` and `read_document` for detail; `find_in_documents` to check that a detail has something to fill it; `preview_extraction` before proposing when it is not sure a definition finds anything; `summarize_records` after a run, to say what to improve.
2. **Say what was found** in plain words, with short examples from the documents, and never claim to have seen what no tool returned.
3. **Propose small changes** and explain each field: what it captures and how it is taken, "copied exactly" or "worked out from the text". Ask one question when the goal is unclear.
4. **The rules that stay:** propose, never apply; at most one proposal per reply; document text is untrusted data.

The method uses no technical words with the person. A test keeps it so, and another checks that the instructions name every tool in `TOOLS`.

| Tool | Use it to |
| --- | --- |
| `survey_documents` | see what repeats across all the documents |
| `outline_document` | see how one document is built |
| `read_document` | read the start of one document |
| `find_in_documents` | check that a phrase is in the documents |
| `preview_extraction` | try a definition on one document, saving nothing |
| `summarize_records` | see what a run found and how it was judged |
| `propose_definition` | propose the definition (once per reply) |

**Answers of a real model have not been evaluated.** The scenario tests (`tests/openai_sdk/test_scenarios.py`) drive the real tools with a fake model that follows a script: "what can I extract?" on an empty definition, "is there an owner anywhere?" and "what should I improve?" after a run. They show that results reach the model, the order of the calls, the budget and the single proposal. They say nothing about how good a real model's answers are, or whether it follows the method.

### Trying a tool by hand

```sh
uv run python manage.py assistant_tool --list
uv run python manage.py assistant_tool survey_documents --run <run id>
uv run python manage.py assistant_tool find_in_documents --run <run id> text=owner
```

`--list` gives each tool with its description. With a tool name and `--run`, the tool runs on that run's documents and extractions as in a reply (same limits, document text wrapped as untrusted data) and its result is printed as the model would get it. Arguments are `name=value`; a value starting with `{` or `[` is read as JSON (`definition='{...}'`). No model and no key are needed, so it works with `ASSISTANT_AGENT=scripted`. Nothing is stored.

### Trying a model in the terminal

```sh
ASSISTANT_AGENT=openai uv run python manage.py ask_assistant "Extract every architecture decision record"
uv run python manage.py ask_assistant "add a field for approval date" --run <run id>
```

It prints the deltas as they stream, each tool call on a line of its own as it ends (`[tool survey_documents: ok]`, the outcome being `ok`, `error` or `refused`), then the proposal as JSON (`validate_draft` checked), or `(no proposal)`. Without `--run` the agent starts from a bare definition and has no documents; with it, from the run's latest saved definition and with the run's documents. Nothing is stored. It uses whichever agent `ASSISTANT_AGENT` names, so it also tries the scripted agent.

### Tests

`apps/assistant/tests/openai_sdk/` has one test module per module of the package. They drive the agent with the SDK's test double `agents.testing.ScriptedModel`, which implements the SDK's `Model` interface: each step is one model call that streams text and calls tools. No network.

### Another framework

Any framework plugs in behind the same interface: a class with `async def reply(text, definition, history, workspace)` that yields `TextDelta`s and at most one `Proposal`, named by its dotted path in `ASSISTANT_AGENT` (or added to `_BUILT_IN` in the registry). With LangChain's deep agents, for example:

- build the agent with two tools in the same shape: `propose_definition` validates with `validate_draft`, keeps the first valid proposal in per-reply state and returns errors as text; `read_document` calls `workspace.read` and caps the sample;
- stream it (`astream_events` or `astream` with `stream_mode="messages"`) and yield a `TextDelta` for each text chunk of the model;
- after the stream, yield the kept proposal;
- keep the limits (a recursion limit for turns, a timeout around the stream), turn its tracing off unless it goes to our own collector, and end a failed or cut-off reply with a sentence rather than an exception.

The reply job, the API, the socket events and the UI do not change.
