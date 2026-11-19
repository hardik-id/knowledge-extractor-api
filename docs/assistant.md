# Assistant

The Studio's chat turns a bare prompt into fields and a template, and adjusts them on request. The assistant proposes; the person applies. The brain behind the chat is an agent, and agents are replaceable. This page covers the conversation API, the reply job, the agent interface and the first agent.

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
| `ASSISTANT_AGENT` | `scripted`, later `openai` | `scripted` |

`get_agent()` in `apps/assistant/agents/registry.py` reads it. An unknown value stops the app at start with a message naming the setting. A value with a dot is read as the dotted path of a class, which is how tests swap in a fake. `openai` is not built yet.
