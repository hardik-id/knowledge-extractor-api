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

`write_reply(message_id)` in `apps/assistant/tasks.py`. It loads the reply and the message it answers, then runs `get_agent().reply(text, definition, history, documents)`:

- `history` is the run's earlier messages, oldest first.
- `documents` are the run's files. They are read through `documents.selectors`, as the run's owner; a document that is not one of the run's files cannot be read (`document_not_found`).

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
def reply(text, definition, history, documents) -> AsyncIterator[AgentEvent]
```

| In | Meaning |
| --- | --- |
| `text` | What the person wrote. |
| `definition` | The definition on their screen, a validated draft (`apps/extraction/validation.py`), saved or not. Snake case, ids filled in. |
| `history` | The conversation so far, oldest first, as `Message(role, text)`. |
| `documents` | `RunDocuments`: `list()` and `read(document_id)`, the run's documents. |

Out: a stream of events. `TextDelta(text)` is new text, not the text so far, so the deltas joined are the reply. `Proposal(definition, reasons)` is a complete definition (not a patch) and `[{ path, reason }]`; there is at most one, after the deltas. The stream ends when the reply is complete. An agent never saves anything: applying a proposal is a normal save of the definition.

Implement it as an `async def` that `yield`s. `apps/assistant/tests/fakes.py` has a fake agent in a few lines.

## The scripted agent

`apps/assistant/agents/scripted.py` ports the UI's `src/services/mock/mock-assistant.ts`: keyword rules, no model, no key, deterministic. It does not read the documents. The header comment of the module lists what it understands. A bare prompt (a definition with no record types) proposes record types and fields; "add", "remove", "rename", "make exact", "make inferred", "split", "can have several values", "output as ..." and "use ... in the template" change the definition; anything else answers with help and no proposal. Proposals have unique keys, a choice field has a choice, and they pass `validate_draft`.

Its reply text is cut into deltas of three words each.

## Choosing the agent

| Setting | Values | Default |
| --- | --- | --- |
| `ASSISTANT_AGENT` | `scripted`, `openai` | `scripted` |

`get_agent()` in `apps/assistant/agents/registry.py` reads it. An unknown value stops the app at start with a message naming the setting. A value with a dot is read as the dotted path of a class, which is how tests swap in a fake.

## The LLM agent

`ASSISTANT_AGENT=openai` chooses `apps/assistant/agents/openai_agent.py`, an agent built with the [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/) (`openai-agents`). It reads the request, the definition on the person's screen, the conversation and, when it wants to, samples of the run's documents, explains itself and proposes a definition.

- **Text.** The model's streamed text becomes `TextDelta`s as it arrives. When the model speaks again after a tool call, the new text starts after a blank line.
- **The proposal** is a call of the tool `propose_definition(definition, reasons)`. Its arguments are checked against a strict JSON schema (the shape of `validate_draft`: modes, value types and formats as enums) and then by `validate_draft`. An invalid proposal goes back to the model as the tool's answer, starting `Error:` and saying what is wrong (where it does not fit the schema, without echoing the values), so it can correct it in the next turn. The first valid proposal is kept and later calls are refused, so at most one reaches the person, after all the text. A record type or field with an empty `id` gets one from `validate_draft`; the instructions tell the model to keep the ids of what stays.
- **`read_document(document_id)`** reads a sample of one of the run's documents, through `RunDocuments` (as the run's owner, only the run's own files).
- **Propose, never apply.** The instructions explain the definition model (record types, fields, `quote` against `inferred`, value types, `multiple`, the output template) and the rule that the assistant proposes and the person applies. No tool saves anything.

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

**Document text is untrusted input.** The instructions say so; a sample comes back between `<document>` and `</document>` with a note to treat it as data, and a `</document>` inside the text is broken up so it cannot close the element. Document text never reaches the instructions or the tools: the tools, the schema and the rule "propose, never apply" are fixed in code, and whatever a document says, the only way to change anything is a proposal the person must apply.

### Limits of a reply

| Limit | Value | When it is reached |
| --- | --- | --- |
| Turns (model calls, tool round trips included) | 8 | the reply is cut off |
| Time per reply | 120 s (below `ASSISTANT_REPLY_TIMEOUT_SECONDS`) | the reply is cut off |

A reply that is cut off ends with "I had to stop here because this reply took too long; please ask again, perhaps for less at once." A model or sign-in error (a wrong key, no network, no Azure identity) ends it with "I could not reach the language model, so I could not finish this reply." A valid proposal made before either still arrives. Either way the reply ends normally with `assistant.done`.

### Logs

The agent logs what happened, never what was said: `assistant_not_configured` (the missing setting names), `assistant_reply_cut_off` (`reason`: `timeout` or `max_turns`), `assistant_model_failed` (the error's class and HTTP status, not its message, which can quote the request or a masked key) and `assistant_proposals_rejected` (a count). The SDK's own logging of model and tool data stays off (its default), and the `openai`, `httpx2` and `httpcore2` loggers never log below `INFO`, whatever `LOG_LEVEL` says: at `DEBUG` they would write request bodies and response headers. No key, token, prompt or document text reaches the logs.

### Trying a model in the terminal

```sh
ASSISTANT_AGENT=openai uv run python manage.py ask_assistant "Extract every architecture decision record"
uv run python manage.py ask_assistant "add a field for approval date" --run <run id>
```

It prints the deltas as they stream, then the proposal as JSON (`validate_draft` checked), or `(no proposal)`. Without `--run` the agent starts from a bare definition and has no documents; with it, from the run's latest saved definition and with the run's documents. Nothing is stored. It uses whichever agent `ASSISTANT_AGENT` names, so it also tries the scripted agent.

### Tests

`apps/assistant/tests/test_openai_agent.py` drives the agent with the SDK's test double `agents.testing.ScriptedModel`, which implements the SDK's `Model` interface: each step is one model call that streams text and calls tools. No network.

### Another framework

Any framework plugs in behind the same interface: a class with `async def reply(text, definition, history, documents)` that yields `TextDelta`s and at most one `Proposal`, named by its dotted path in `ASSISTANT_AGENT` (or added to `_BUILT_IN` in the registry). With LangChain's deep agents, for example:

- build the agent with two tools in the same shape: `propose_definition` validates with `validate_draft`, keeps the first valid proposal in per-reply state and returns errors as text; `read_document` calls `documents.read` and caps the sample;
- stream it (`astream_events` or `astream` with `stream_mode="messages"`) and yield a `TextDelta` for each text chunk of the model;
- after the stream, yield the kept proposal;
- keep the limits (a recursion limit for turns, a timeout around the stream), turn its tracing off unless it goes to our own collector, and end a failed or cut-off reply with a sentence rather than an exception.

The reply job, the API, the socket events and the UI do not change.
