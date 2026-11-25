# Security: CORS and response headers

All of it is configured in `config/settings/base.py` (section "Security") and `production.py`.

## CORS

- Origins come from `CORS_ALLOWED_ORIGINS` (comma separated, default `http://localhost:3000`). A `*` stops startup. `CORS_ALLOW_ALL_ORIGINS` is off.
- Allowed request headers: Django-CORS defaults plus `X-Request-ID`, `traceparent`, `tracestate` and `baggage` (so `Authorization` and `Content-Type` are included).
- Exposed response headers: `ETag`, `X-Request-ID` and `Server-Timing` (the trace id, see [observability.md](observability.md)).
- No credentials: `Access-Control-Allow-Credentials` is never sent, because the UI sends a bearer token and no cookies.
- The middleware sits right after the request id and log middleware, before everything else, so preflights and errors carry the headers too.

django-cors-headers 4.9.0 declares support up to Django 6.0; it has no release that names 6.1. It runs unchanged on 6.1 and the tests cover it. Revisit when a release names 6.1.

## Security headers

| Header | Value | Where |
| --- | --- | --- |
| `X-Content-Type-Options` | `nosniff` | `SECURE_CONTENT_TYPE_NOSNIFF` |
| `Referrer-Policy` | `same-origin` | `SECURE_REFERRER_POLICY` |
| `X-Frame-Options` | `DENY` | `X_FRAME_OPTIONS` |
| `Strict-Transport-Security` | one year, include subdomains | production only |
| `Content-Security-Policy` | see below | `SECURE_CSP` |

## Content-Security-Policy

Django's built-in `ContentSecurityPolicyMiddleware` and `SECURE_CSP` send an enforced policy: everything from `'self'`, images also from `data:`, no plugins, `frame-ancestors 'none'`. The admin renders under it. When Swagger UI is added (#20), allow it per view with `CSP.NONCE` or a view-level override, not by loosening the global policy.

## What leaves the system

With `ASSISTANT_AGENT=openai` the person's messages, definitions and the document text the assistant reads go to the configured model provider (`LLM_PROVIDER`: OpenAI, Azure OpenAI or, for local testing, Anthropic). With `EXTRACTOR=llm` the text of every document that is run, the prompt, the record types and up to five example records go there too, one call per file. Requests are sent with `store=False` and the SDK's tracing to OpenAI is off. Logs, spans and metrics never carry document text, quotes, values or prompts ([observability.md](observability.md)). The model has no tools, and the document is wrapped as data (see [extraction.md](extraction.md)).

## Custom chunking is a prototype without isolation

With `CUSTOM_CHUNKING=local` a language model writes Python (a text splitter) from a person's description, and the server then runs that code on documents. Any signed-in person can also save code as `chunking.custom.code` in a configuration, and it runs on the next extraction. Nothing confines it: the agent's shell commands and the saved code run as the server's own user and can read whatever that user can, including the server's environment (through `/proc`), `.env`, signing keys and the home directory. The network is cut (`unshare -rn`) only where the machine allows it; where it does not (a default Docker container), the code has the server's network and one warning is logged. Commands have a time, CPU, memory, file-size and output limit and are killed as a process group, but none of this is a security boundary.

Generate sends up to 5 documents (60,000 characters each) and the linked page to the model provider. Instructions in a document or a linked page could steer the agent (prompt injection); it is told they are data, which is not a guarantee. The linked page is fetched by the server (https only, public addresses only, no redirects, size and time caps; [extraction.md](extraction.md)), never by the sandbox.

So the setting is `off` by default, `local` needs `AUTH_MODE=dev` (a single developer machine) and production settings refuse it; both stop at start. Use it only with documents and links you trust. Using it for real needs a sandbox that isolates (a container or a hosted one) and a way to tie saved code to what generate returned.
