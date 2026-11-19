# Assistant

The Studio's chat turns a bare prompt into fields and a template, and adjusts them on request. The assistant proposes; the person applies. The brain behind the chat is an agent, and agents are replaceable. This page covers the agent interface and the first agent. The endpoints and the stored conversation come with #146.

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
