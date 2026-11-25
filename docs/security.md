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

With `CUSTOM_CHUNKING=local` a language model writes Python (a text splitter) from a person's description, and the server then runs that code on documents. The Agents SDK's local sandbox (`UnixLocalSandboxClient`) adds no OS-level confinement on Linux: the agent's shell commands and the saved code run as the server's own user, with its files and its network (only the sandbox's environment variables start empty). The runner sets a time limit, a memory and a file-size limit, and the interpreter runs in isolated mode; none of these is a security boundary. Instructions in a document or in a linked page could steer the agent (it is told they are data, which is not a guarantee). So the setting is `off` by default, production settings refuse `local` and stop at start, and it is for local testing only. The linked page is fetched by the server with the checks described in [extraction.md](extraction.md) (https only, public addresses only, no redirects, size and time caps), never by the sandbox. Using it for real needs a sandbox that isolates (a container or a hosted one) first.
