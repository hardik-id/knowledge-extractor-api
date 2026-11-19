# Trying it by hand

This page starts the whole stack and walks through every Studio call, first through the UI, then with curl. It needs Docker, `make` and `python3`. The UI part also needs Node.

## Start the stack

```sh
cp .env.example .env     # once; .env is ignored by git
make up                  # docker compose up -d --build --wait
```

`make up` builds the image and starts five services: `db` (PostgreSQL), `redis`, `otel-collector`, `api` and `worker`. It returns when all five are healthy. Check:

```sh
docker compose ps
curl localhost:8000/api/v1/health
```

`api` and `worker` run the same image with the same settings: sign-in mode `dev`, `ASSISTANT_AGENT=scripted`, `EXTRACTOR=scripted`, and telemetry sent to the collector. Compose sets these itself, so a `.env` copied from `.env.example` is enough. The host ports (`API_PORT`, `DB_PORT`, `REDIS_PORT`, `OTEL_HTTP_PORT`) can be changed in `.env`; the commands below assume 8000.

```sh
make logs                # follow api, worker and collector output
make token               # a dev token, valid for eight hours
make ui-env              # the .env.local for the UI, with a fresh token
```

A dev token is signed by a key kept inside the `api` container. When the `api` container is recreated (for example by `make up` after a code change) the key is new and older tokens are refused: run `make token` or `make ui-env` again.

## The UI

```sh
git clone https://github.com/hardik-id/knowledge-extractor.git
cd knowledge-extractor
npm ci
make -C ../knowledge-extractor-api -s ui-env > .env.local    # adjust the path to this repository
npm run dev
```

`make ui-env` prints these five lines:

```
NEXT_PUBLIC_BACKEND_MODE=http
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1
NEXT_PUBLIC_WS_BASE_URL=ws://localhost:8000
NEXT_PUBLIC_APPS=studio
NEXT_PUBLIC_DEV_ACCESS_TOKEN=<a fresh token>
```

Open http://localhost:3000/studio. Pick a document, press Run, ask the assistant for a change. The UI sends the token with every request; the token lasts eight hours, then run `make ui-env` again and restart `npm run dev`.

## The API, with curl

Everything below runs in one shell, from the top. The commands print JSON; `show` makes it readable, `pick` takes one field out of it.

```sh
API=http://localhost:8000/api/v1
TOKEN=$(make -s token)
show() { python3 -m json.tool; }
pick() { python3 -c 'import json,sys; print(json.load(sys.stdin)[sys.argv[1]])' "$1"; }
call() { curl -s -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' "$@"; }
```

### Who am I

```sh
call $API/me | show
```

```json
{ "id": 1, "name": "Dev User", "preferred_username": "devuser@dev.invalid" }
```

Without the token the answer is 401 `{ "code": "unauthenticated", ... }`.

### Documents

```sh
call $API/documents | show                 # { "items": [ ... ] }, the sample documents
DOC=enriched/engineering/architecture/architecture-decisions-2026.md
call $API/documents/$DOC                   # read one: the Markdown text
```

The text starts with `---` front matter, then `# Architecture decisions 2026`, and holds three decisions (`## ADR-012: ...` to `## ADR-014: ...`).

### Create a run

```sh
RUN=$(call -d "{\"items\":[{\"source\":\"storage\",\"source_ref\":\"$DOC\"}]}" $API/runs)
echo "$RUN" | show
RUN_ID=$(echo "$RUN" | pick id)
FILE_ID=$(echo "$RUN" | python3 -c 'import json,sys; print(json.load(sys.stdin)["files"][0]["id"])')
```

The answer (201) has the run `id`, one entry in `files` and one entry in `cells` with `"stage": "extract"` and `"status": "pending"`.

### Definition

```sh
call $API/runs/$RUN_ID/stages/extract/definition | show
```

Version 1: the prompt, one record type `ADR` with six fields, and a Markdown output template. Save a new version by sending the draft with the version it was edited from (`base_version`):

```sh
call $API/runs/$RUN_ID/stages/extract/definition | python3 -c '
import json,sys
d = json.load(sys.stdin)
d["base_version"] = d.pop("version")
d["prompt"] = "Extract every architecture decision record (ADR), exactly as written."
print(json.dumps(d))' > draft.json
call -X PUT -d @draft.json $API/runs/$RUN_ID/stages/extract/definition | pick version
```

```
2
```

Sending a `base_version` that is not the latest is a 409 `definition_conflict`.

### Watch the socket

Open a second terminal in this directory and leave it running while you do the next steps:

```sh
TOKEN=$(make -s token) uv run python scripts/watch_run.py <RUN_ID>
```

Replace `<RUN_ID>` with the value of `$RUN_ID`. The script asks for a ticket, connects to `ws://localhost:8000/ws/runs/<RUN_ID>/` and prints one JSON line per event. `API_URL` (default `http://localhost:8000`) points it elsewhere. A close with code 4401 means the ticket was refused, 4404 that the run is not yours or is gone. Events sent while nobody listens are lost, so start the watcher first.

### The assistant

```sh
python3 -c '
import json
d = json.load(open("draft.json"))
del d["base_version"]
print(json.dumps({"text": "Add a field for the owner", "definition": d}))' > message.json
call -d @message.json $API/runs/$RUN_ID/extraction/assistant/messages | show
```

The answer (201) is your message, `"role": "user"`. The reply is written by the worker. The watcher prints `assistant.delta` events (the text, piece by piece), one `assistant.proposal` (a definition and the reason for each field) and `assistant.done`. Read the whole conversation:

```sh
call $API/runs/$RUN_ID/extraction/assistant/messages | show
```

The second message is `"role": "assistant"`, `"status": "done"`, with a `proposal`. The assistant only proposes; applying it is a `PUT` of the definition.

### Execute

```sh
call -X POST -d "{\"file_ids\":[\"$FILE_ID\"],\"config\":{\"definition_version\":2}}" \
  $API/runs/$RUN_ID/stages/extract/executions | show
```

`definition_version` is the latest saved version. The answer is 202 with `execution_id`, `stage` and `file_ids`. The watcher prints `cell` events for `queued`, `running` and `succeeded`, then `extraction.changed` with `"revision": 1`. The run's snapshot has the same state:

```sh
call $API/runs/$RUN_ID | show
```

### Records

```sh
call $API/runs/$RUN_ID/files/$FILE_ID/extraction > extraction.json
python3 -m json.tool extraction.json | head -40
```

`revision` is 1, `definition_version` is the one that ran, and `records` lists the extracted records. They are the three ADRs, each with `"origin": "llm"` and `"review": "suggested"`, and each value with the quote span it came from.

### One correction

Accept the first record. The `revision` in the body must be the current one, or the answer is 409 `revision_conflict`.

```sh
REC_ID=$(python3 -c 'import json; print(json.load(open("extraction.json"))["records"][0]["id"])')
call -X PATCH -d '{"revision":1,"review":"accepted"}' \
  $API/runs/$RUN_ID/files/$FILE_ID/extraction/records/$REC_ID | python3 -c '
import json,sys; d=json.load(sys.stdin); print("revision", d["revision"], d["records"][0]["review"])'
```

```
revision 2 accepted
```

The watcher prints `extraction.changed` with `"revision": 2`. The other corrections (add or delete a record, replace a field's values, accept or reject one value) are in [extraction.md](extraction.md) and the Swagger UI at http://localhost:8000/api/docs.

Clean up the run when you are done:

```sh
call -X DELETE $API/runs/$RUN_ID -o /dev/null -w '%{http_code}\n'    # 204
rm extraction.json draft.json message.json
```

The watcher stops with close code 4404.

## Telemetry

`api` and `worker` send traces, metrics and logs to the collector over OTLP. The collector prints everything it receives:

```sh
docker compose logs otel-collector | grep -E 'service.name: Str\(knowledge-extractor-(api|worker)\)' | sort | uniq -c
```

Both `knowledge-extractor-api` and `knowledge-extractor-worker` appear. Look for one request's trace in `make logs`: log lines carry `trace_id`. To send telemetry on to Splunk, set the `SPLUNK_*` variables in `.env` and run `make up` again (see [observability.md](observability.md)).

## Switching the assistant to a model

The stack uses the scripted assistant, which needs no key. To use a model, set these in your own `.env` (never commit it):

```
ASSISTANT_AGENT=openai
LLM_PROVIDER=openai
LLM_MODEL=<model name>
OPENAI_API_KEY=<your key>
```

For Azure OpenAI use `LLM_PROVIDER=azure`, `LLM_MODEL=<deployment name>` and `AZURE_OPENAI_ENDPOINT`. Compose passes `.env` to `api` and `worker`, then:

```sh
make up
```

Compose recreates `api` and `worker`. Send an assistant message again; the reply now comes from the model. Switch back by restoring `scripted`.

## Stopping and resetting

```sh
docker compose stop api worker       # stop the two, keep everything else
make up                              # start again
```

`db`, `redis` and `otel-collector` are shared by every checkout of this repository on the machine. Stop them only when nobody else uses them: `docker compose stop db redis otel-collector`. To delete all data, including every other checkout's database, `docker compose down -v`. To start from empty tables without touching the containers, use your own database name in `DATABASE_URL` instead.
